"""Pydantic-схемы (валидация входящих данных и сериализация ответов)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.defaults import BET_STATUSES

BetStatus = Literal["pending", "won", "lost", "push", "cancelled"]


# --- Источники --------------------------------------------------------------
class SourceBase(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    url: str | None = Field(default=None, max_length=500)
    enabled: bool = True
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Название источника обязательно")
        return value


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    url: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None
    notes: str | None = None


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str | None = None
    enabled: bool
    notes: str | None = None
    reliability: float | None = None
    bets_count: int = 0
    staked: float = 0.0
    payout: float = 0.0
    profit: float = 0.0
    roi: float | None = None
    last_status: str | None = None
    last_stake: float | None = None
    created_at: datetime
    updated_at: datetime


# --- Ставки -----------------------------------------------------------------
class BetLegIn(BaseModel):
    """Составное событие экспресса при создании ставки."""

    event_name: str = Field(min_length=3, max_length=300)
    prediction: str | None = Field(default=None, max_length=120)
    coefficient: float = Field(gt=1.0, le=1000.0)
    status: BetStatus = "pending"

    @field_validator("event_name")
    @classmethod
    def _strip_event(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Название события обязательно")
        return value

    @field_validator("prediction")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class BetBase(BaseModel):
    sport: str = Field(min_length=2, max_length=60)
    event_name: str | None = Field(default=None, max_length=300)
    prediction: str | None = Field(default=None, max_length=120)
    # Для экспресса коэффициент считается по составным событиям, поэтому не обязателен.
    coefficient: float | None = Field(default=None, gt=1.0, le=1000.0)
    stake: float = Field(gt=0, le=10_000_000)
    source_id: int | None = None
    source_name: str | None = Field(default=None, max_length=120)
    comment: str | None = Field(default=None, max_length=2000)
    created_at: datetime | None = None

    @field_validator("event_name", "sport", "prediction", "comment", "source_name")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class BetCreate(BetBase):
    kind: Literal["single", "express"] = "single"
    status: BetStatus = "pending"
    legs: list[BetLegIn] = Field(default_factory=list)
    screenshot_token: str | None = None  # тестовая фича: скриншот ставки для Telegram

    @model_validator(mode="after")
    def _validate_shape(self) -> "BetCreate":
        if self.kind == "express":
            if len(self.legs) < 2:
                raise ValueError("В экспрессе должно быть не меньше двух событий")
        else:
            if self.legs:
                raise ValueError("Составные события допустимы только для экспресса")
            if not self.event_name or len(self.event_name) < 3:
                raise ValueError("Укажите название события (минимум 3 символа)")
            if self.coefficient is None:
                raise ValueError("Укажите коэффициент (больше 1.00)")
        return self


class BetUpdate(BaseModel):
    sport: str | None = Field(default=None, min_length=2, max_length=60)
    event_name: str | None = Field(default=None, min_length=3, max_length=300)
    prediction: str | None = Field(default=None, max_length=120)
    coefficient: float | None = Field(default=None, gt=1.0, le=1000.0)
    stake: float | None = Field(default=None, gt=0, le=10_000_000)
    source_id: int | None = None
    comment: str | None = Field(default=None, max_length=2000)
    status: BetStatus | None = None


class BetResultUpdate(BaseModel):
    """Ручная корректировка результата ставки."""

    status: Literal["won", "lost", "push", "cancelled"]
    payout: float | None = Field(default=None, ge=0)
    comment: str | None = Field(default=None, max_length=2000)


class BetLegResultUpdate(BaseModel):
    """Результат отдельного события экспресса."""

    status: Literal["pending", "won", "lost", "push", "cancelled"]


class BetBulkIn(BaseModel):
    """Массовое действие над выбранными ставками."""

    ids: list[int] = Field(min_length=1)
    action: Literal["delete", "status"]
    status: BetStatus | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> "BetBulkIn":
        if self.action == "status" and self.status is None:
            raise ValueError("Укажите статус для массового изменения")
        return self


class BetListOut(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class BetRecognitionLeg(BaseModel):
    """Событие экспресса, распознанное со скриншота."""

    event_name: str | None = None
    prediction: str | None = None
    coefficient: float | None = None


class BetRecognitionOut(BaseModel):
    """Поля ставки, распознанные со скриншота."""

    kind: Literal["single", "express"] = "single"
    event_name: str | None = None
    prediction: str | None = None
    coefficient: float | None = None
    stake: float | None = None
    legs: list[BetRecognitionLeg] = Field(default_factory=list)
    raw_text: str = ""
    screenshot_token: str | None = None  # тестовая фича: токен скриншота для Telegram


# --- Баланс (банкролл) ------------------------------------------------------
CashFlowKind = Literal["deposit", "withdrawal"]


class CashFlowIn(BaseModel):
    """Операция по счёту: пополнение или вывод средств."""

    kind: CashFlowKind
    amount: float = Field(gt=0, le=100_000_000)
    occurred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=200)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class CashFlowUpdate(BaseModel):
    kind: CashFlowKind | None = None
    amount: float | None = Field(default=None, gt=0, le=100_000_000)
    occurred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=200)


class CashFlowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    amount: float
    occurred_at: datetime
    note: str | None = None


# --- Настройки --------------------------------------------------------------
class SettingsOut(BaseModel):
    values: dict[str, Any]
    meta: dict[str, Any]


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


class TelegramChatOut(BaseModel):
    """Найденная группа бота для уведомлений."""

    chat_id: str
    title: str = ""
    is_admin: bool = False
    status: str = ""
    warning: str = ""


# --- Разное -----------------------------------------------------------------
class ActionResult(BaseModel):
    ok: bool = True
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


# --- Вспомогательное --------------------------------------------------------
def normalize_status(value: str) -> str:
    if value not in BET_STATUSES:
        raise ValueError(f"Недопустимый статус: {value}")
    return value
