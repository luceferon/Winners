"""Справочники и настройки по умолчанию."""

from __future__ import annotations

# --- Статусы ставок ---------------------------------------------------------
STATUS_PENDING = "pending"
STATUS_WON = "won"
STATUS_LOST = "lost"
STATUS_PUSH = "push"
STATUS_CANCELLED = "cancelled"

BET_STATUSES = (STATUS_PENDING, STATUS_WON, STATUS_LOST, STATUS_PUSH, STATUS_CANCELLED)

STATUS_LABELS = {
    STATUS_PENDING: "Активная",
    STATUS_WON: "Выигрышная",
    STATUS_LOST: "Проигрышная",
    STATUS_PUSH: "Возврат",
    STATUS_CANCELLED: "Отменена",
}

# Статусы, которые считаются завершёнными (расчёт выполнен).
SETTLED_STATUSES = (STATUS_WON, STATUS_LOST, STATUS_PUSH, STATUS_CANCELLED)

# --- Виды спорта ------------------------------------------------------------
SPORTS = [
    "Футбол",
    "Хоккей",
    "Баскетбол",
    "Теннис",
    "Волейбол",
    "Гандбол",
    "Бейсбол",
    "Американский футбол",
    "Единоборства",
    "Киберспорт",
    "Другое",
]

# --- Настройки по умолчанию -------------------------------------------------
DEFAULT_SETTINGS: dict[str, object] = {
    # Уведомления
    "notifications_enabled": True,
    "notify_on_settle": True,
    "notify_on_failure": True,
    # Отображение
    "currency": "RUB",
    "theme": "dark",
    "default_range": "30d",
    "stats_show_roi": True,
    "compact_tables": False,
    # Банкролл и сайзинг (0 — ограничение выключено)
    "bankroll_goal": 0.0,
    "stop_loss_percent": 0.0,
    "max_stake_percent": 0.0,
    # Сохранённые фильтры истории ставок
    "history_filters": {},
    # Порядок панелей на странице статистики (массив data-panel; пустой — по умолчанию)
    "stats_panel_order": [],
}

# Границы периода по умолчанию (дней). 0 — «всё время».
RANGE_PRESETS = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "365d": 365,
    "all": 0,
    "custom": 0,
}
