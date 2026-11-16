"""Служебные маршруты: состояние приложения и управление демо-данными."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import APP_VERSION
from app.database import get_db
from app.models import Bet, Source
from app.seed import clear_all_data, is_empty, seed_demo_data

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Проверка работоспособности и краткая сводка по данным."""
    counts = {
        "bets": int(db.execute(select(func.count(Bet.id))).scalar_one()),
        "sources": int(db.execute(select(func.count(Source.id))).scalar_one()),
        "active": int(
            db.execute(select(func.count(Bet.id)).where(Bet.status == "pending")).scalar_one()
        ),
    }
    return {
        "status": "ok",
        "version": APP_VERSION,
        "counts": counts,
        "empty": is_empty(db),
    }


@router.post("/system/demo")
def load_demo(db: Session = Depends(get_db)) -> dict:
    """Загрузить демонстрационный набор данных."""
    return seed_demo_data(db, force=True)


@router.delete("/system/data")
def wipe_data(keep_sources: bool = False, db: Session = Depends(get_db)) -> dict:
    """Удалить все ставки, события и журнал парсинга."""
    result = clear_all_data(db, keep_sources=keep_sources)
    return {"ok": True, **result}
