"""Работа со временем: локальная зона, границы суток, бизнес-даты."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import TIMEZONE

_FALLBACK_OFFSET = timedelta(hours=8)


def get_tz() -> timezone | ZoneInfo:
    """Локальная зона из настроек. При отсутствии tzdata — фиксированный сдвиг."""
    try:
        return ZoneInfo(TIMEZONE)
    except Exception:  # pragma: no cover - зависит от окружения
        return timezone(_FALLBACK_OFFSET)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(get_tz())


def local_date(value: datetime | None) -> date | None:
    local = to_local(value)
    return local.date() if local else None


def local_date_str(value: datetime | None) -> str | None:
    day = local_date(value)
    return day.isoformat() if day else None


def day_start_utc(day: date) -> datetime:
    """Начало локальных суток, выраженное в UTC."""
    return datetime.combine(day, time.min, tzinfo=get_tz()).astimezone(timezone.utc)


def day_end_utc(day: date) -> datetime:
    """Конец локальных суток (23:59:59.999999), выраженный в UTC."""
    return datetime.combine(day, time.max, tzinfo=get_tz()).astimezone(timezone.utc)


def resolve_range(
    preset: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Преобразовать пресет/даты в границы диапазона (UTC)."""
    from app.defaults import RANGE_PRESETS

    today = datetime.now(get_tz()).date()
    if date_from or date_to:
        start = day_start_utc(date_from) if date_from else None
        end = day_end_utc(date_to or today) if date_to else None
        return start, end

    days = RANGE_PRESETS.get(preset or "30d", 30)
    if not days:
        return None, None
    return day_start_utc(today - timedelta(days=days - 1)), day_end_utc(today)
