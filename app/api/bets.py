"""Маршруты раздела истории ставок."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from sqlalchemy.orm import Session

from app import export
from app.database import get_db
from app.defaults import SETTLED_STATUSES
from app.models import Bet, BetLeg
from app.schemas import (
    ActionResult,
    BetBulkIn,
    BetCreate,
    BetLegResultUpdate,
    BetListOut,
    BetRecognitionOut,
    BetResultUpdate,
    BetUpdate,
)
from app.services import bets_service, ocr_service, screenshot_store, telegram_service, timeutil
from app.services.bets_service import BetError
from app.services.ocr_service import OcrError, OcrUnavailableError

router = APIRouter(prefix="/api/bets", tags=["bets"])


def _bounds(date_from: date | None, date_to: date | None) -> tuple[datetime | None, datetime | None]:
    return (
        timeutil.day_start_utc(date_from) if date_from else None,
        timeutil.day_end_utc(date_to) if date_to else None,
    )


def _list_params(
    status_filter: str | None,
    kind: str | None,
    sport: str | None,
    source_id: int | None,
    search: str | None,
    date_from: date | None,
    date_to: date | None,
) -> dict:
    start, end = _bounds(date_from, date_to)
    return {
        "status": status_filter,
        "kind": kind,
        "sport": sport,
        "source_id": source_id,
        "search": search,
        "date_from": start,
        "date_to": end,
    }


@router.get("", response_model=BetListOut)
def list_bets(
    status_filter: str | None = Query(None, alias="status"),
    kind: str | None = Query(None, pattern="^(single|express)$"),
    sport: str | None = Query(None),
    source_id: int | None = Query(None),
    search: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    sort: str = Query("created_at"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> BetListOut:
    """Полная история ставок с фильтрацией, поиском и сортировкой."""
    filters = _list_params(
        status_filter, kind, sport, source_id, search, date_from, date_to
    )
    items, total = bets_service.list_bets(
        db, limit=limit, offset=offset, sort=sort, order=order, **filters
    )
    return BetListOut(
        items=[bet.as_dict() for bet in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/settlements/feed")
def settlements_feed(
    since: datetime | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    """Лента рассчитанных ставок (для уведомлений о результатах)."""
    bets = bets_service.settlement_feed(db, since=since, limit=limit)
    return {"items": [bet.as_dict() for bet in bets]}


@router.get("/export")
def export_bets(
    status_filter: str | None = Query(None, alias="status"),
    kind: str | None = Query(None, pattern="^(single|express)$"),
    sport: str | None = Query(None),
    source_id: int | None = Query(None),
    search: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    sort: str = Query("created_at"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(export.EXPORT_LIMIT, ge=1, le=export.EXPORT_LIMIT),
    db: Session = Depends(get_db),
) -> Response:
    """Выгрузка истории ставок в CSV с теми же фильтрами, что и список."""
    filters = _list_params(
        status_filter, kind, sport, source_id, search, date_from, date_to
    )
    items, _total = bets_service.list_bets(
        db, limit=limit, offset=0, sort=sort, order=order, **filters
    )
    filename = f"winners-bets-{date.today().isoformat()}.csv"
    return export.csv_response(filename, export.bets_rows(items), header=export.BETS_HEADER)


@router.get("/suggest")
def suggest(
    q: str = Query("", description="Часть названия события"),
    limit: int = Query(8, ge=1, le=20),
    db: Session = Depends(get_db),
) -> dict:
    """Подсказки по ранее введённым событиям для автодополнения."""
    return {"items": bets_service.suggest(db, q, limit=limit)}


@router.post("/bulk")
def bulk(payload: BetBulkIn, db: Session = Depends(get_db)) -> dict:
    """Массовое удаление или смена статуса выбранных ставок."""
    try:
        return bets_service.bulk_action(db, payload.ids, payload.action, status=payload.status)
    except BetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/recognize", response_model=BetRecognitionOut)
def recognize_bet(file: UploadFile | None = File(default=None)) -> BetRecognitionOut:
    """Распознать ставку со скриншота — из загруженного файла или буфера обмена."""
    try:
        data: bytes | None = None
        if file is not None:
            data = file.file.read()
        if not data:
            data = ocr_service.read_clipboard_image()
        if not data:
            raise HTTPException(
                status_code=400,
                detail="В буфере обмена нет изображения. Скопируйте скриншот и повторите.",
            )
        parsed, boxes = ocr_service.parse_image_full(data)
        result = BetRecognitionOut(**parsed)
        # тестовая фича: сохраняем скриншот, чтобы отправить его в Telegram
        # вместе с уведомлением о новой ставке (с замазанной суммой)
        result.screenshot_token = screenshot_store.store(data, boxes or [])
        return result
    except (OcrUnavailableError, OcrError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{bet_id}")
def get_bet(bet_id: int, db: Session = Depends(get_db)) -> dict:
    bet = db.get(Bet, bet_id)
    if bet is None:
        raise HTTPException(status_code=404, detail="Ставка не найдена")
    return bet.as_dict()


@router.post("/{bet_id}/duplicate", status_code=201)
def duplicate_bet(bet_id: int, db: Session = Depends(get_db)) -> dict:
    """Создать новую активную ставку на основе существующей."""
    bet = db.get(Bet, bet_id)
    if bet is None:
        raise HTTPException(status_code=404, detail="Ставка не найдена")
    return bets_service.duplicate_bet(db, bet).as_dict()


@router.post("", status_code=201)
def create_bet(
    payload: BetCreate, background: BackgroundTasks, db: Session = Depends(get_db)
) -> dict:
    """Добавить новую ставку вручную."""
    try:
        bet = bets_service.create_bet(db, payload)
    except BetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # тестовая фича: если при создании передан токен скриншота,
    # замазываем сумму и отправляем фото в Telegram. Любая ошибка
    # замазывания не должна мешать сохранению ставки.
    photo: bytes | None = None
    stored = screenshot_store.retrieve(payload.screenshot_token)
    if stored is not None:
        try:
            photo = ocr_service.blur_stake_region(
                stored.image_bytes, stored.boxes, stake_value=bet.stake
            )
        except Exception:
            import logging

            logging.getLogger("winners.bets").exception(
                "Не удалось замазать сумму на скриншоте — фото отправлено не будет"
            )
            photo = None
    telegram_service.queue_bet_notification(
        background, db, bet.as_dict(), event="created", photo=photo
    )
    return bet.as_dict()


@router.put("/{bet_id}")
def update_bet(bet_id: int, payload: BetUpdate, db: Session = Depends(get_db)) -> dict:
    bet = db.get(Bet, bet_id)
    if bet is None:
        raise HTTPException(status_code=404, detail="Ставка не найдена")
    try:
        bet = bets_service.update_bet(db, bet, payload)
    except BetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return bet.as_dict()


@router.delete("/{bet_id}", response_model=ActionResult)
def delete_bet(bet_id: int, db: Session = Depends(get_db)) -> ActionResult:
    bet = db.get(Bet, bet_id)
    if bet is None:
        raise HTTPException(status_code=404, detail="Ставка не найдена")
    bets_service.delete_bet(db, bet)
    return ActionResult(message=f"Ставка #{bet_id} удалена")


@router.patch("/{bet_id}/result")
def set_result(
    bet_id: int,
    payload: BetResultUpdate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    """Ручная корректировка результата ставки."""
    bet = db.get(Bet, bet_id)
    if bet is None:
        raise HTTPException(status_code=404, detail="Ставка не найдена")
    if bet.is_express:
        raise HTTPException(
            status_code=400, detail="Для экспресса отметьте результат каждого события"
        )
    previous_status = bet.status
    bet = bets_service.set_result(
        db,
        bet,
        payload.status,
        payout=payload.payout,
        auto=False,
        comment=payload.comment,
    )
    # Уведомляем только о смене статуса на рассчитанный, чтобы повторное
    # сохранение того же результата не давало дубль в Telegram.
    if bet.status != previous_status and bet.status in SETTLED_STATUSES:
        telegram_service.queue_bet_notification(background, db, bet.as_dict(), event="settled")
    return bet.as_dict()


@router.patch("/{bet_id}/legs/{leg_id}/result")
def set_leg_result(
    bet_id: int,
    leg_id: int,
    payload: BetLegResultUpdate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    """Отметить результат отдельного события экспресса."""
    bet = db.get(Bet, bet_id)
    if bet is None:
        raise HTTPException(status_code=404, detail="Ставка не найдена")
    leg = db.get(BetLeg, leg_id)
    if leg is None or leg.bet_id != bet_id:
        raise HTTPException(status_code=404, detail="Событие экспресса не найдено")
    was_pending = bet.status == "pending"
    try:
        bet = bets_service.set_leg_result(db, bet, leg, payload.status)
    except BetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Одно уведомление на экспресс — когда отмечена последняя нога.
    if was_pending and bet.status in SETTLED_STATUSES:
        telegram_service.queue_bet_notification(background, db, bet.as_dict(), event="settled")
    return bet.as_dict()
