"""Модели данных: источники, ставки, настройки."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    """Текущее время в UTC (aware)."""
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Хранит время в UTC, возвращает aware-datetime в UTC.

    SQLite не хранит tzinfo, поэтому нормализуем значение на входе и выходе,
    чтобы бизнес-даты не «съезжали» при отображении в локальном времени.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Source(Base):
    """Источник ставок: букмекер, прогнозист, канал или собственный анализ."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    url: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    bets: Mapped[list["Bet"]] = relationship(back_populates="source")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "enabled": self.enabled,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class Bet(Base):
    """Ставка пользователя."""

    __tablename__ = "bets"
    __table_args__ = (
        Index("ix_bets_status", "status"),
        Index("ix_bets_created_at", "created_at"),
        Index("ix_bets_sport", "sport"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="single")
    sport: Mapped[str] = mapped_column(String(60), nullable=False)
    event_name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_event_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    prediction: Mapped[str | None] = mapped_column(String(120))
    coefficient: Mapped[float] = mapped_column(Float, nullable=False)
    stake: Mapped[float] = mapped_column(Float, nullable=False)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    source_name: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    payout: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    source: Mapped[Source | None] = relationship(back_populates="bets")
    legs: Mapped[list["BetLeg"]] = relationship(
        back_populates="bet",
        cascade="all, delete-orphan",
        order_by="BetLeg.id",
    )

    @property
    def is_express(self) -> bool:
        """Экспресс — ставка из нескольких событий (ног)."""
        return self.kind == "express"

    @property
    def potential_payout(self) -> float:
        return round(self.stake * self.coefficient, 2)

    @property
    def profit(self) -> float:
        """Финансовый результат по ставке (0 для активных)."""
        if self.status == "won":
            return round(self.payout - self.stake, 2)
        if self.status == "lost":
            return round(-self.stake, 2)
        if self.status == "push":
            return 0.0
        return 0.0

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "sport": self.sport,
            "event_name": self.event_name,
            "prediction": self.prediction,
            "coefficient": self.coefficient,
            "stake": self.stake,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "status": self.status,
            "payout": self.payout,
            "profit": self.profit,
            "potential_payout": self.potential_payout,
            "comment": self.comment,
            "created_at": self.created_at,
            "settled_at": self.settled_at,
        }
        if self.kind == "express":
            data["legs"] = [leg.as_dict() for leg in self.legs]
        return data


class BetLeg(Base):
    """Составное событие экспресса (нога): событие, прогноз, коэффициент и результат."""

    __tablename__ = "bet_legs"
    __table_args__ = (Index("ix_bet_legs_bet_id", "bet_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bet_id: Mapped[int] = mapped_column(
        ForeignKey("bets.id", ondelete="CASCADE"), nullable=False
    )
    event_name: Mapped[str] = mapped_column(String(300), nullable=False)
    prediction: Mapped[str | None] = mapped_column(String(120))
    coefficient: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    bet: Mapped["Bet"] = relationship(back_populates="legs")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "bet_id": self.bet_id,
            "event_name": self.event_name,
            "prediction": self.prediction,
            "coefficient": self.coefficient,
            "status": self.status,
        }


class CashFlow(Base):
    """Операция по счёту: пополнение или вывод средств (без учёта ставок)."""

    __tablename__ = "cash_flows"
    __table_args__ = (Index("ix_cash_flows_occurred_at", "occurred_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="deposit")
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "amount": self.amount,
            "occurred_at": self.occurred_at,
            "note": self.note,
            "created_at": self.created_at,
        }


class Setting(Base):
    """Настройки приложения (key → JSON-значение)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
