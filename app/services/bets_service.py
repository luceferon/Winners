"""Бизнес-логика работы со ставками."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Bet, BetLeg, Source, utcnow
from app.schemas import BetCreate, BetUpdate
from app.textutils import normalize_title

SORT_FIELDS = {
    "created_at": Bet.created_at,
    "event_name": Bet.event_name,
    "sport": Bet.sport,
    "coefficient": Bet.coefficient,
    "stake": Bet.stake,
    "status": Bet.status,
    "settled_at": Bet.settled_at,
    "id": Bet.id,
}


class BetError(ValueError):
    """Ошибка бизнес-логики ставок."""


def _resolve_source(db: Session, source_id: int | None, fallback_name: str | None) -> str | None:
    if source_id is None:
        return fallback_name
    source = db.get(Source, source_id)
    if source is None:
        raise BetError(f"Источник с id={source_id} не найден")
    return source.name


def _legs_coefficient(legs: list) -> float:  # noqa: ANN001 - принимает BetLegIn или BetLeg
    """Итоговый коэффициент экспресса: произведение кэфов, возврат считается за 1.00."""
    value = 1.0
    for leg in legs:
        if getattr(leg, "status", "pending") in {"push", "cancelled"}:
            continue
        value *= float(leg.coefficient)
    return round(value, 2)


def _express_name(legs: list) -> str:  # noqa: ANN001
    """Название экспресса: перечисление событий-ног."""
    return " + ".join(leg.event_name for leg in legs)[:300]


def recompute_express(db: Session, bet: Bet) -> Bet:
    """Пересчитать итог экспресса по статусам ног.

    Правила: проигрыш любой ноги → экспресс проигран; возврат/отмена ноги →
    её коэффициент считается как 1.0; если хотя бы одна нога активна, экспресс
    ещё не рассчитан; иначе выплата = сумма × произведение выигравших ног.
    """
    legs = bet.legs
    if not legs:
        return bet

    bet.coefficient = _legs_coefficient(legs)

    if any(leg.status == "lost" for leg in legs):
        status, payout = "lost", 0.0
    elif any(leg.status == "pending" for leg in legs):
        status, payout = "pending", 0.0
    elif any(leg.status == "won" for leg in legs):
        effective = 1.0
        for leg in legs:
            if leg.status == "won":
                effective *= leg.coefficient
        status, payout = "won", round(bet.stake * effective, 2)
    else:
        # все ноги — возврат/отмена
        status, payout = "push", round(bet.stake, 2)

    bet.status = status
    bet.payout = payout
    bet.settled_at = None if status == "pending" else utcnow()
    return bet


def create_bet(db: Session, payload: BetCreate) -> Bet:
    """Создать новую ставку (одиночную или экспресс)."""
    source_name = _resolve_source(db, payload.source_id, payload.source_name)
    is_express = payload.kind == "express"

    if is_express:
        event_name = payload.event_name or _express_name(payload.legs)
        coefficient = _legs_coefficient(payload.legs)
    else:
        event_name = payload.event_name
        coefficient = float(payload.coefficient)

    bet = Bet(
        kind=payload.kind,
        sport=payload.sport,
        event_name=event_name,
        normalized_event_name=normalize_title(event_name),
        prediction=payload.prediction,
        coefficient=coefficient,
        stake=float(payload.stake),
        source_id=payload.source_id,
        source_name=source_name,
        status=payload.status,
        comment=payload.comment,
        created_at=payload.created_at or utcnow(),
    )
    db.add(bet)
    db.flush()

    if is_express:
        for leg in payload.legs:
            db.add(
                BetLeg(
                    bet_id=bet.id,
                    event_name=leg.event_name,
                    prediction=leg.prediction,
                    coefficient=float(leg.coefficient),
                    status=leg.status,
                )
            )
        db.flush()
        recompute_express(db, bet)

    db.commit()
    db.refresh(bet)
    return bet


def update_bet(db: Session, bet: Bet, payload: BetUpdate) -> Bet:
    """Изменить параметры ставки (без расчёта результата)."""
    data = payload.model_dump(exclude_unset=True)

    # У экспресса итоговый коэффициент вычисляется из ног — не даём его перезаписать.
    if bet.is_express:
        data.pop("coefficient", None)
        data.pop("status", None)

    if "source_id" in data:
        bet.source_name = _resolve_source(db, data["source_id"], bet.source_name)
        bet.source_id = data["source_id"]
    if "event_name" in data and data["event_name"]:
        bet.event_name = data["event_name"]
        bet.normalized_event_name = normalize_title(data["event_name"])
    for field in ("sport", "prediction", "coefficient", "stake", "comment", "status"):
        if field in data and data[field] is not None:
            setattr(bet, field, data[field])

    if bet.status != "pending" and bet.settled_at is None:
        bet.settled_at = utcnow()

    db.commit()
    db.refresh(bet)
    return bet


def delete_bet(db: Session, bet: Bet) -> None:
    db.delete(bet)
    db.commit()


def compute_payout(bet: Bet, status: str, payout: float | None = None) -> float:
    """Рассчитать выплату по новому статусу."""
    if payout is not None:
        return round(float(payout), 2)
    if status == "won":
        return round(bet.stake * bet.coefficient, 2)
    if status == "push":
        return round(bet.stake, 2)
    return 0.0


def set_result(
    db: Session,
    bet: Bet,
    status: str,
    *,
    payout: float | None = None,
    auto: bool = False,
    comment: str | None = None,
) -> Bet:
    """Установить результат ставки (автоматически или вручную)."""
    if status not in {"won", "lost", "push", "cancelled", "pending"}:
        raise BetError(f"Недопустимый статус: {status}")

    # Итог экспресса всегда выводится из статусов ног.
    if bet.is_express:
        recompute_express(db, bet)
        db.commit()
        db.refresh(bet)
        return bet

    bet.status = status
    bet.payout = compute_payout(bet, status, payout)
    if comment is not None:
        bet.comment = comment

    if status == "pending":
        bet.settled_at = None
        bet.payout = 0.0
    else:
        bet.settled_at = utcnow()

    db.commit()
    db.refresh(bet)
    return bet


def set_leg_result(db: Session, bet: Bet, leg: BetLeg, status: str) -> Bet:
    """Отметить результат отдельного события экспресса и пересчитать итог."""
    if not bet.is_express:
        raise BetError("Ставка не является экспрессом")
    if status not in {"won", "lost", "push", "cancelled", "pending"}:
        raise BetError(f"Недопустимый статус: {status}")

    leg.status = status
    recompute_express(db, bet)
    db.commit()
    db.refresh(bet)
    return bet


def build_query(
    *,
    status: str | None = None,
    status_in: list[str] | None = None,
    kind: str | None = None,
    sport: str | None = None,
    source_id: int | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    exclude_status: str | None = None,
):
    stmt = select(Bet).options(selectinload(Bet.legs))
    if kind and kind != "all":
        stmt = stmt.where(Bet.kind == kind)
    if status and status != "all":
        stmt = stmt.where(Bet.status == status)
    if status_in:
        stmt = stmt.where(Bet.status.in_(status_in))
    if exclude_status:
        stmt = stmt.where(Bet.status != exclude_status)
    if sport and sport != "all":
        stmt = stmt.where(Bet.sport == sport)
    if source_id:
        stmt = stmt.where(Bet.source_id == source_id)
    if date_from is not None:
        stmt = stmt.where(Bet.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Bet.created_at <= date_to)
    if search:
        raw = search.strip()
        pattern = f"%{raw.lower()}%"
        conditions = [
            func.lower(Bet.prediction).like(pattern),
            func.lower(Bet.comment).like(pattern),
            func.lower(Bet.sport).like(pattern),
            func.lower(Bet.source_name).like(pattern),
        ]
        # SQLite не умеет приводить кириллицу к нижнему регистру, поэтому по
        # названию события ищем по заранее нормализованному полю.
        normalized = normalize_title(raw)
        if normalized:
            conditions.append(Bet.normalized_event_name.like(f"%{normalized}%"))
        stmt = stmt.where(or_(*conditions))
    return stmt


def list_bets(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    sort: str = "created_at",
    order: str = "desc",
    **filters: Any,
) -> tuple[list[Bet], int]:
    stmt = build_query(**filters)
    total = db.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ).scalar_one()

    column = SORT_FIELDS.get(sort, Bet.created_at)
    stmt = stmt.order_by(column.asc() if order == "asc" else column.desc(), Bet.id.desc())
    rows = db.execute(stmt.limit(limit).offset(offset)).unique().scalars().all()
    return list(rows), int(total)


def available_sports(db: Session) -> list[str]:
    rows = db.execute(select(Bet.sport).distinct().order_by(Bet.sport)).scalars().all()
    return [row for row in rows if row]


def last_bet_of_source(db: Session, source_id: int) -> Bet | None:
    """Последняя по дате создания ставка источника (активная тоже учитывается)."""
    return db.execute(
        select(Bet)
        .where(Bet.source_id == source_id)
        .order_by(Bet.created_at.desc(), Bet.id.desc())
        .limit(1)
    ).scalars().first()


def settlement_feed(db: Session, since: datetime | None = None, limit: int = 20) -> list[Bet]:
    """Последние рассчитанные ставки (для уведомлений)."""
    stmt = (
        select(Bet)
        .options(selectinload(Bet.legs))
        .where(Bet.settled_at.is_not(None))
        .order_by(Bet.settled_at.desc())
        .limit(limit)
    )
    if since is not None:
        stmt = stmt.where(Bet.settled_at > since)
    return list(db.execute(stmt).unique().scalars().all())


def duplicate_bet(db: Session, bet: Bet) -> Bet:
    """Создать новую активную ставку-копию (для экспресса — с ногами в pending)."""
    copy = Bet(
        kind=bet.kind,
        sport=bet.sport,
        event_name=bet.event_name,
        normalized_event_name=bet.normalized_event_name,
        prediction=bet.prediction,
        coefficient=bet.coefficient,
        stake=bet.stake,
        source_id=bet.source_id,
        source_name=bet.source_name,
        status="pending",
        payout=0.0,
        comment=bet.comment,
        created_at=utcnow(),
    )
    db.add(copy)
    db.flush()

    if bet.is_express:
        for leg in bet.legs:
            db.add(
                BetLeg(
                    bet_id=copy.id,
                    event_name=leg.event_name,
                    prediction=leg.prediction,
                    coefficient=leg.coefficient,
                    status="pending",
                )
            )
        db.flush()
        recompute_express(db, copy)

    db.commit()
    db.refresh(copy)
    return copy


def bulk_action(
    db: Session,
    ids: list[int],
    action: str,
    *,
    status: str | None = None,
) -> dict[str, Any]:
    """Массовое действие над ставками: удаление или смена статуса.

    Статус меняется только у одиночных ставок: результат экспресса всегда
    выводится из статусов его событий, поэтому экспрессы при смене статуса
    пропускаются (учитываются в ``skipped``).
    """
    if not ids:
        raise BetError("Не выбрано ни одной ставки")

    bets = list(
        db.execute(
            select(Bet).options(selectinload(Bet.legs)).where(Bet.id.in_(ids))
        ).unique().scalars().all()
    )
    if not bets:
        raise BetError("Ставки не найдены")

    if action == "delete":
        for bet in bets:
            db.delete(bet)
        db.commit()
        return {"action": "delete", "affected": len(bets), "skipped": 0}

    if action != "status":
        raise BetError(f"Неизвестное действие: {action}")
    if status not in {"pending", "won", "lost", "push", "cancelled"}:
        raise BetError(f"Недопустимый статус: {status}")

    affected = 0
    skipped = 0
    for bet in bets:
        if bet.is_express:
            skipped += 1
            continue
        bet.status = status
        bet.payout = compute_payout(bet, status)
        bet.settled_at = None if status == "pending" else utcnow()
        affected += 1
    db.commit()
    return {"action": "status", "status": status, "affected": affected, "skipped": skipped}


def suggest(db: Session, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Подсказки по ранее введённым событиям (последнее вхождение каждого)."""
    normalized = normalize_title(query or "")
    stmt = select(Bet).options(selectinload(Bet.legs))
    if normalized:
        stmt = stmt.where(Bet.normalized_event_name.like(f"%{normalized}%"))
    stmt = stmt.order_by(Bet.created_at.desc(), Bet.id.desc())

    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for bet in db.execute(stmt).unique().scalars():
        key = bet.normalized_event_name
        if not key or key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "event_name": bet.event_name,
                "sport": bet.sport,
                "prediction": bet.prediction,
                "coefficient": bet.coefficient,
                "source_id": bet.source_id,
                "source_name": bet.source_name,
            }
        )
        if len(items) >= limit:
            break
    return items
