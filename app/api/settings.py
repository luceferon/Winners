"""Маршруты раздела настроек."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import APP_VERSION
from app.database import get_db
from app.defaults import (
    BET_STATUSES,
    RANGE_PRESETS,
    SPORTS,
    STATUS_LABELS,
)
from app.schemas import ActionResult, SettingsOut, SettingsUpdate
from app.services import settings_service, telegram_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _meta(db: Session, values: dict) -> dict:
    return {
        "version": APP_VERSION,
        "sports": list(SPORTS),
        "statuses": [{"value": key, "label": STATUS_LABELS[key]} for key in BET_STATUSES],
        "ranges": list(RANGE_PRESETS.keys()),
    }


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)) -> SettingsOut:
    """Текущие настройки и справочники для интерфейса."""
    values = settings_service.get_settings(db)
    return SettingsOut(values=values, meta=_meta(db, values))


@router.put("", response_model=SettingsOut)
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> SettingsOut:
    """Обновить настройки (частично)."""
    try:
        values = settings_service.update_settings(db, payload.values)
    except settings_service.SettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SettingsOut(values=values, meta=_meta(db, values))


@router.post("/reset", response_model=ActionResult)
def reset_settings(db: Session = Depends(get_db)) -> ActionResult:
    """Сбросить настройки к значениям по умолчанию."""
    settings_service.reset_settings(db)
    return ActionResult(message="Настройки сброшены к значениям по умолчанию")


@router.post("/telegram/test", response_model=ActionResult)
def test_telegram(db: Session = Depends(get_db)) -> ActionResult:
    """Отправить тестовое сообщение в Telegram с текущими настройками."""
    ok, error = telegram_service.send_test_message(settings_service.get_settings(db))
    if not ok:
        raise HTTPException(status_code=400, detail=f"Telegram: {error}")
    return ActionResult(message="Тестовое сообщение отправлено в Telegram")
