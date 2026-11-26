"""Конфигурация приложения: пути, БД, параметры по умолчанию."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

DATA_DIR = Path(os.getenv("WINNERS_DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "winners.db"
DATABASE_URL = os.getenv("WINNERS_DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}")

LOG_FILE = DATA_DIR / "winners.log"

APP_TITLE = "Winners — статистика спортивных ставок"
APP_VERSION = "2.2.0"

# Заполнять базу демонстрационными данными при первом запуске (пустая БД).
SEED_DEMO_ON_EMPTY = os.getenv("WINNERS_SEED_DEMO", "1") not in {"0", "false", "False"}

TIMEZONE = os.getenv("WINNERS_TIMEZONE", "Asia/Shanghai")
