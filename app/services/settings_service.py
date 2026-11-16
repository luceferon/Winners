"""Хранение и валидация настроек приложения."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.defaults import DEFAULT_SETTINGS
from app.models import Setting


class SettingsError(ValueError):
    """Некорректное значение настройки."""


def _coerce(key: str, value: Any) -> Any:
    """Привести значение к типу значения по умолчанию."""
    default = DEFAULT_SETTINGS[key]
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "да"}
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise SettingsError(f"Настройка «{key}» ожидает целое число") from exc
        return number
    if isinstance(default, float):
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise SettingsError(f"Настройка «{key}» ожидает число") from exc
    if isinstance(default, (dict, list)):
        if not isinstance(value, type(default)):
            raise SettingsError(f"Настройка «{key}» ожидает значение типа {type(default).__name__}")
        return value
    return "" if value is None else str(value)


def validate_values(values: dict[str, Any]) -> dict[str, Any]:
    """Проверить и нормализовать набор настроек."""
    result: dict[str, Any] = {}
    for key, raw in values.items():
        if key not in DEFAULT_SETTINGS:
            raise SettingsError(f"Неизвестная настройка: {key}")
        result[key] = _coerce(key, raw)
    return result


def get_settings(db: Session) -> dict[str, Any]:
    """Актуальные настройки: значения из БД поверх значений по умолчанию."""
    merged = dict(DEFAULT_SETTINGS)
    for row in db.execute(select(Setting)).scalars():
        merged[row.key] = row.value
    return merged


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    row = db.get(Setting, key)
    if row is not None:
        return row.value
    return DEFAULT_SETTINGS.get(key, default)


def update_settings(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    """Сохранить переданные настройки (частичное обновление)."""
    clean = validate_values(values)
    for key, value in clean.items():
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
    db.commit()
    return get_settings(db)


def reset_settings(db: Session) -> dict[str, Any]:
    """Сбросить пользовательские настройки к значениям по умолчанию."""
    for row in db.execute(select(Setting)).scalars():
        db.delete(row)
    db.commit()
    return get_settings(db)
