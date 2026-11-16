"""Тесты сервиса настроек: нормализация, валидация, сброс."""

from __future__ import annotations

import pytest

from app.defaults import DEFAULT_SETTINGS
from app.services import settings_service


def test_defaults_are_returned(db):
    values = settings_service.get_settings(db)
    assert values["currency"] == "RUB"
    assert values["theme"] == "dark"
    assert values["notifications_enabled"] is True


def test_update_persists_values(db):
    updated = settings_service.update_settings(db, {"theme": "light", "currency": "USD"})
    assert updated["theme"] == "light"
    assert settings_service.get_settings(db)["currency"] == "USD"


def test_unknown_key_raises(db):
    with pytest.raises(settings_service.SettingsError):
        settings_service.update_settings(db, {"unknown_setting": 1})


def test_bool_coercion_from_string(db):
    updated = settings_service.update_settings(db, {"notifications_enabled": "false"})
    assert updated["notifications_enabled"] is False


def test_reset_returns_defaults(db):
    settings_service.update_settings(db, {"theme": "light", "currency": "USD"})
    values = settings_service.reset_settings(db)
    assert values["theme"] == DEFAULT_SETTINGS["theme"]
    assert values["currency"] == DEFAULT_SETTINGS["currency"]


def test_get_setting_fallback(db):
    assert settings_service.get_setting(db, "currency") == "RUB"
    assert settings_service.get_setting(db, "missing", "default") == "default"
