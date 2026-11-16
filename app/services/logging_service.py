"""Журналирование приложения в консоль и файл."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.config import LOG_FILE

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """Настроить логирование в консоль и файл (идемпотентно)."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    handler = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(fmt)
    root.addHandler(handler)

    _configured = True
