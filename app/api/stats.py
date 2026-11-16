"""Маршруты раздела общей статистики."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app import export
from app.database import get_db
from app.services import statistics_service

router = APIRouter(prefix="/api/stats", tags=["statistics"])


@router.get("/summary")
def summary(
    preset: str = Query("30d", description="Пресет периода: 7d, 30d, 90d, 365d, all, custom"),
    date_from: date | None = Query(None, description="Начало периода (YYYY-MM-DD)"),
    date_to: date | None = Query(None, description="Конец периода (YYYY-MM-DD)"),
    sport: str | None = Query(None),
    source_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    """Сводная статистика за выбранный период с разбивками для графиков."""
    return statistics_service.summary(
        db,
        preset=preset,
        date_from=date_from,
        date_to=date_to,
        sport=sport,
        source_id=source_id,
    )


@router.get("/options")
def options(db: Session = Depends(get_db)) -> dict:
    """Доступные значения фильтров: виды спорта, источники, границы дат."""
    return statistics_service.options(db)


@router.get("/compare")
def compare(
    preset: str = Query("30d", description="Пресет периода: 7d, 30d, 90d, 365d, all, custom"),
    date_from: date | None = Query(None, description="Начало периода (YYYY-MM-DD)"),
    date_to: date | None = Query(None, description="Конец периода (YYYY-MM-DD)"),
    sport: str | None = Query(None),
    source_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    """Сравнение текущего периода с предыдущим такой же длительности."""
    return statistics_service.compare(
        db,
        preset=preset,
        date_from=date_from,
        date_to=date_to,
        sport=sport,
        source_id=source_id,
    )


@router.get("/export")
def export_stats(
    preset: str = Query("30d", description="Пресет периода: 7d, 30d, 90d, 365d, all, custom"),
    date_from: date | None = Query(None, description="Начало периода (YYYY-MM-DD)"),
    date_to: date | None = Query(None, description="Конец периода (YYYY-MM-DD)"),
    sport: str | None = Query(None),
    source_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> Response:
    """Выгрузка сводки статистики в CSV: показатели и разбивки по спорту и источникам."""
    data = statistics_service.summary(
        db,
        preset=preset,
        date_from=date_from,
        date_to=date_to,
        sport=sport,
        source_id=source_id,
    )
    filename = f"winners-stats-{date.today().isoformat()}.csv"
    return export.csv_response(filename, export.stats_rows(data))
