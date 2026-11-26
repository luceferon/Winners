"""Журналирование приложения в консоль и файл."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.config import LOG_FILE

_configured = False


def configure_console_utf8() -> None:
    """Перевести стандартный вывод в UTF-8, чтобы кириллица не терялась в консоли.

    В консоли с не-UTF-8 кодовой страницей кириллица выводится знаками вопроса,
    поэтому кодовая страница переключается на 65001, а потоки перенастраиваются.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass


def setup_logging(level: int = logging.INFO) -> None:
    """Настроить логирование в консоль и файл (идемпотентно)."""
    global _configured
    if _configured:
        return

    configure_console_utf8()

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
