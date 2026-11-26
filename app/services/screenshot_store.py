"""Временное хранилище скриншотов ставок (тестовая фича).

Скриншот, с которого распознана ставка, хранится в памяти недолго, чтобы
отправить его в Telegram вместе с уведомлением о новой ставке (с замазанной
суммой). Если фича не понравится — достаточно удалить этот модуль и вызовы
``store``/``retrieve`` в ``app/api/bets.py``.

Хранилище потокобезопасное: ``BackgroundTasks`` FastAPI выполняются в том же
процессе, но возможен конкурентный доступ из нескольких запросов.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import NamedTuple


class StoredScreenshot(NamedTuple):
    """Сохранённый скриншот и распознанные строки с координатами."""

    image_bytes: bytes
    boxes: list  # list[OcrLine] из ocr_service
    created_at: float


_TTL_SECONDS = 600  # 10 минут — хватает, чтобы заполнить форму и сохранить ставку.

_store: dict[str, StoredScreenshot] = {}
_lock = threading.Lock()


def _purge_expired_locked(now: float | None = None) -> None:
    """Удалить просроченные записи. Вызывается под ``_lock``."""
    now = time.time() if now is None else now
    expired = [
        key for key, value in _store.items() if now - value.created_at > _TTL_SECONDS
    ]
    for key in expired:
        _store.pop(key, None)


def store(image_bytes: bytes, boxes: list) -> str:
    """Сохранить скриншот и вернуть токен для последующего извлечения."""
    token = uuid.uuid4().hex
    with _lock:
        _purge_expired_locked()
        _store[token] = StoredScreenshot(image_bytes, list(boxes), time.time())
    return token


def retrieve(token: str | None) -> StoredScreenshot | None:
    """Вернуть скриншот по токену или ``None`` (токен пустой/просрочен)."""
    if not token:
        return None
    with _lock:
        _purge_expired_locked()
        item = _store.get(token)
        if item is None:
            return None
        if time.time() - item.created_at > _TTL_SECONDS:
            _store.pop(token, None)
            return None
        return item


def clear() -> None:
    """Очистить хранилище (для тестов)."""
    with _lock:
        _store.clear()
