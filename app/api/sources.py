"""Маршруты управления источниками ставок."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Bet, Source
from app.schemas import ActionResult, SourceCreate, SourceOut, SourceUpdate
from app.services import bets_service

router = APIRouter(prefix="/api/sources", tags=["sources"])

SOURCE_SORTS = {
    "name": lambda row: row["name"].lower(),
    "reliability": lambda row: row["reliability"] if row["reliability"] is not None else -1.0,
    "roi": lambda row: row["roi"] if row["roi"] is not None else float("-inf"),
    "bets_count": lambda row: row["bets_count"],
    "profit": lambda row: row["profit"],
}


@router.get("", response_model=list[SourceOut])
def list_sources(
    sort: str = Query("name", description="Поле сортировки: name, reliability, roi, bets_count, profit"),
    order: str | None = Query(None, pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Все источники ставок с количеством ставок, результатом и доходностью."""
    rows = db.execute(select(Source).order_by(Source.name)).scalars().all()
    items = [_source_output(db, source) for source in rows]

    key = SOURCE_SORTS.get(sort, SOURCE_SORTS["name"])
    if order is None:
        order = "asc" if sort == "name" else "desc"
    items.sort(key=key, reverse=(order == "desc"))
    return items


@router.post("", response_model=SourceOut, status_code=201)
def create_source(payload: SourceCreate, db: Session = Depends(get_db)) -> dict:
    source = Source(**payload.model_dump())
    db.add(source)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Источник с таким названием уже существует") from exc
    db.refresh(source)
    return _source_output(db, source)


@router.put("/{source_id}", response_model=SourceOut)
def update_source(source_id: int, payload: SourceUpdate, db: Session = Depends(get_db)) -> dict:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Источник не найден")

    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(source, key, value)

    if "name" in data and data["name"]:
        db.execute(Bet.__table__.update().where(Bet.source_id == source.id).values(source_name=data["name"]))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Источник с таким названием уже существует") from exc
    db.refresh(source)
    return _source_output(db, source)


@router.delete("/{source_id}", response_model=ActionResult)
def delete_source(source_id: int, db: Session = Depends(get_db)) -> ActionResult:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Источник не найден")

    linked = db.execute(select(func.count(Bet.id)).where(Bet.source_id == source_id)).scalar_one()
    name = source.name
    db.delete(source)
    db.commit()
    return ActionResult(
        message=f"Источник «{name}» удалён" + (f", ставки сохранены (отвязано: {linked})" if linked else ""),
        details={"unlinked_bets": int(linked)},
    )


def _source_output(db: Session, source: Source) -> dict:
    stats = db.execute(
        select(
            func.count(Bet.id),
            func.coalesce(func.sum(case((Bet.status == "won", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Bet.status == "lost", 1), else_=0)), 0),
            func.coalesce(func.sum(Bet.stake), 0.0),
            func.coalesce(func.sum(Bet.payout), 0.0),
            func.coalesce(func.sum(case((Bet.status.in_(("won", "lost", "push")), Bet.stake), else_=0)), 0.0),
        ).where(Bet.source_id == source.id)
    ).one()
    decided = int(stats[1]) + int(stats[2])
    settled_stake = float(stats[5])
    payout = float(stats[4])
    profit = payout - settled_stake
    last = bets_service.last_bet_of_source(db, source.id)
    return {
        "id": source.id,
        "name": source.name,
        "url": source.url,
        "enabled": source.enabled,
        "notes": source.notes,
        "reliability": round(int(stats[1]) / decided * 100, 1) if decided else None,
        "bets_count": int(stats[0]),
        "staked": round(float(stats[3]), 2),
        "payout": round(payout, 2),
        "profit": round(profit, 2),
        "roi": round(profit / settled_stake * 100, 1) if settled_stake else None,
        "last_status": last.status if last else None,
        "last_stake": round(last.stake, 2) if last else None,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }
