"""Тесты временного хранилища скриншотов (тестовая фича)."""

from __future__ import annotations

import time

from app.services import screenshot_store
from app.services.ocr_service import OcrLine


def test_store_and_retrieve():
    screenshot_store.clear()
    token = screenshot_store.store(b"png-data", [])
    assert token

    item = screenshot_store.retrieve(token)
    assert item is not None
    assert item.image_bytes == b"png-data"


def test_retrieve_unknown_token_returns_none():
    screenshot_store.clear()
    assert screenshot_store.retrieve("missing") is None
    assert screenshot_store.retrieve(None) is None


def test_retrieve_keeps_boxes():
    screenshot_store.clear()
    boxes = [OcrLine("Ставка 100 руб.", 10, 20, 100, 40)]
    token = screenshot_store.store(b"data", boxes)
    item = screenshot_store.retrieve(token)
    assert item is not None
    assert item.boxes == boxes


def test_expired_item_is_not_returned(monkeypatch):
    screenshot_store.clear()
    token = screenshot_store.store(b"data", [])

    fixed_future = time.time() + screenshot_store._TTL_SECONDS + 10  # noqa: SLF001

    def fake_time():
        return fixed_future

    monkeypatch.setattr(screenshot_store.time, "time", fake_time)
    assert screenshot_store.retrieve(token) is None


def test_purge_removes_expired(monkeypatch):
    screenshot_store.clear()
    token = screenshot_store.store(b"data", [])

    fixed_future = time.time() + screenshot_store._TTL_SECONDS + 10  # noqa: SLF001

    def fake_time():
        return fixed_future

    monkeypatch.setattr(screenshot_store.time, "time", fake_time)
    screenshot_store.store(b"new", [])  # purge вызывается внутри store
    assert screenshot_store.retrieve(token) is None
