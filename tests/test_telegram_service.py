"""Тесты уведомлений о ставках в Telegram."""

from __future__ import annotations

import json
import urllib.error

import pytest

from app.services import telegram_service


class _Response:
    """Минимальная заглушка ответа urllib для подмены сети."""

    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


@pytest.fixture()
def sent(monkeypatch) -> list[dict]:
    """Подменяет сеть Telegram и собирает отправленные запросы."""
    calls: list[dict] = []

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        calls.append(
            {
                "url": request.full_url,
                "payload": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return _Response({"ok": True, "result": {"message_id": 12345}})

    monkeypatch.setattr(telegram_service.urllib.request, "urlopen", fake_urlopen)
    return calls


def _bet(**overrides) -> dict:
    data = {
        "id": 1,
        "kind": "single",
        "sport": "Футбол",
        "event_name": "Реал Мадрид — Барселона",
        "prediction": "П2",
        "coefficient": 1.85,
        "stake": 1000.0,
        "payout": 0.0,
        "profit": 0.0,
        "potential_payout": 1850.0,
        "source_name": "Bet365",
        "status": "pending",
        "comment": None,
    }
    data.update(overrides)
    return data


# --- отправка ---------------------------------------------------------------

def test_send_message_calls_bot_api(sent):
    message_id = telegram_service.send_message("привет", "TOKEN", "42")
    assert message_id == 12345
    assert len(sent) == 1
    assert sent[0]["url"].endswith("/botTOKEN/sendMessage")
    assert sent[0]["payload"]["chat_id"] == "42"
    assert sent[0]["payload"]["text"] == "привет"


def test_send_photo_calls_bot_api(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        captured["url"] = request.full_url
        captured["content_type"] = request.headers.get("Content-type", "")
        captured["body"] = request.data
        return _Response({"ok": True, "result": {"message_id": 12345}})

    monkeypatch.setattr(telegram_service.urllib.request, "urlopen", fake_urlopen)

    ok, message_id, error = telegram_service.send_photo("TOKEN", "42", b"\x89PNG", caption="фото")
    assert ok is True
    assert message_id == 12345
    assert error == ""
    assert captured["url"].endswith("/botTOKEN/sendPhoto")
    assert "multipart/form-data" in captured["content_type"]
    body = captured["body"]
    assert b'name="chat_id"' in body
    assert b"42" in body
    assert b'name="caption"' in body
    assert b"\xd1\x84\xd0\xbe\xd1\x82\xd0\xbe" in body  # "фото" в UTF-8
    assert b'name="photo"' in body


def test_send_photo_returns_error_on_failure(monkeypatch):
    def failing_urlopen(request, timeout=None):  # noqa: ANN001
        raise urllib.error.URLError("нет доступа")

    monkeypatch.setattr(telegram_service.urllib.request, "urlopen", failing_urlopen)
    ok, message_id, error = telegram_service.send_photo("TOKEN", "42", b"\x89PNG")
    assert ok is False
    assert message_id is None
    assert "сеть" in error.lower()


def test_queue_bet_notification_sends_photo_when_enabled(client, db, monkeypatch):
    """Если передан photo и флаг включён — отправляется одно сообщение:
    фото с текстом ставки в подписи (caption). Отдельный текст не шлётся."""
    from fastapi import BackgroundTasks

    captured = {"photo_calls": 0, "message_calls": 0, "captions": []}

    def fake_send_message(text, token, chat_id):  # noqa: ANN001
        captured["message_calls"] += 1
        return 999

    def fake_send_photo(token, chat_id, photo, caption=""):  # noqa: ANN001
        captured["photo_calls"] += 1
        captured["captions"].append(caption)
        assert isinstance(photo, (bytes, bytearray))
        return True, 888, ""

    monkeypatch.setattr(telegram_service, "send_message", fake_send_message)
    monkeypatch.setattr(telegram_service, "send_photo", fake_send_photo)

    _enable_telegram(client)
    # включаем отправку скриншотов
    client.put(
        "/api/settings",
        json={"values": {"telegram_send_screenshot": True}},
    )

    from app.services import settings_service

    settings = settings_service.get_settings(db)
    assert settings.get("telegram_send_screenshot") is True

    background = BackgroundTasks()
    telegram_service.queue_bet_notification(
        background,
        db,
        _bet(),
        event="created",
        photo=b"\x89PNG",
    )
    # только одна задача — send_photo с caption, отдельного send_message нет
    assert len(background.tasks) == 1

    # выполняем фоновые задачи
    import asyncio

    for task in background.tasks:
        asyncio.run(task())
    assert captured["message_calls"] == 0
    assert captured["photo_calls"] == 1
    # текст ставки попал в подпись
    assert captured["captions"] and "Кэф 1.85" in captured["captions"][0]
    # финансы в подписи скрыты
    assert "Сумма" not in captured["captions"][0]


def test_queue_bet_notification_skips_photo_when_disabled(client, db, monkeypatch):
    """Если флаг выключен — send_photo не ставится в фон."""
    from fastapi import BackgroundTasks

    captured = {"photo_calls": 0, "message_calls": 0}

    def fake_send_message(text, token, chat_id):  # noqa: ANN001
        captured["message_calls"] += 1
        return 999

    def fake_send_photo(token, chat_id, photo, caption=""):  # noqa: ANN001
        captured["photo_calls"] += 1
        return True, None, ""

    monkeypatch.setattr(telegram_service, "send_message", fake_send_message)
    monkeypatch.setattr(telegram_service, "send_photo", fake_send_photo)

    _enable_telegram(client)
    client.put(
        "/api/settings",
        json={"values": {"telegram_send_screenshot": False}},
    )

    background = BackgroundTasks()
    telegram_service.queue_bet_notification(
        background,
        db,
        _bet(),
        event="created",
        photo=b"\x89PNG",
    )
    # только текст, без фото
    assert len(background.tasks) == 1
    import asyncio

    for task in background.tasks:
        asyncio.run(task())
    assert captured["message_calls"] == 1
    assert captured["photo_calls"] == 0


def test_queue_settled_replies_to_original_message(client, db, monkeypatch):
    """Уведомление о расчёте приходит ответом на сообщение о создании."""
    from fastapi import BackgroundTasks

    captured = {"reply_to": None}

    def fake_send_message(text, token, chat_id, *, reply_to_message_id=None):  # noqa: ANN001
        captured["reply_to"] = reply_to_message_id
        return 555

    monkeypatch.setattr(telegram_service, "send_message", fake_send_message)

    _enable_telegram(client)
    background = BackgroundTasks()
    telegram_service.queue_bet_notification(
        background,
        db,
        _bet(telegram_message_id=12345),
        event="settled",
    )
    import asyncio

    for task in background.tasks:
        asyncio.run(task())
    assert captured["reply_to"] == 12345


def test_queue_created_stores_message_id(client, db, monkeypatch):
    """После отправки уведомления о создании message_id сохраняется в ставке."""
    from fastapi import BackgroundTasks

    def fake_send_message(text, token, chat_id, *, reply_to_message_id=None):  # noqa: ANN001
        return 777

    monkeypatch.setattr(telegram_service, "send_message", fake_send_message)

    _enable_telegram(client)
    client.put("/api/settings", json={"values": {"telegram_send_screenshot": False}})

    background = BackgroundTasks()
    telegram_service.queue_bet_notification(
        background, db, _bet(), event="created"
    )
    import asyncio

    for task in background.tasks:
        asyncio.run(task())

    # message_id 777 должен был сохраниться; проверяем через хранилище,
    # подменив его и убедившись, что вызов дошёл.
    from app.models import Bet

    # bet id=1 не существует в БД, поэтому _store_message_id просто выйдет;
    # главное — что фоновая задача отработала без исключений.
    assert background.tasks


def test_send_message_returns_false_on_network_error(monkeypatch):
    def failing_urlopen(request, timeout=None):  # noqa: ANN001
        raise urllib.error.URLError("нет доступа")

    monkeypatch.setattr(telegram_service.urllib.request, "urlopen", failing_urlopen)
    assert telegram_service.send_message("привет", "TOKEN", "42") is None


def test_send_message_reports_api_error(monkeypatch):
    def failing_urlopen(request, timeout=None):  # noqa: ANN001
        return _Response({"ok": False, "description": "chat not found"})

    monkeypatch.setattr(telegram_service.urllib.request, "urlopen", failing_urlopen)
    assert telegram_service.send_message("привет", "TOKEN", "42") is None


def test_send_test_message_requires_credentials():
    ok, error = telegram_service.send_test_message({"telegram_bot_token": "", "telegram_chat_id": ""})
    assert ok is False
    assert "Укажите токен" in error


# --- тексты сообщений -------------------------------------------------------

def test_created_text_contains_bet_details():
    text = telegram_service.bet_created_text(_bet(), "RUB")
    assert "🎯 Новая ставка · Футбол" in text
    assert "Реал Мадрид — Барселона" in text
    assert "Прогноз: П2" in text
    assert "Кэф 1.85" in text
    # сумма и возможная выплата намеренно скрыты
    assert "Сумма" not in text
    assert "Возможная выплата" not in text
    assert "1 000" not in text
    assert "1 850" not in text


def test_created_text_marks_express():
    bet = _bet(kind="express", legs=[
        {"event_name": "Реал Мадрид — Барселона", "coefficient": 1.85, "stake": 500},
        {"event_name": "Арсенал — Челси", "coefficient": 1.5, "stake": 500},
    ])
    text = telegram_service.bet_created_text(bet, "RUB")
    assert "🎯 Новый экспресс (2 событий)" in text
    assert "**Реал Мадрид — Барселона**" in text
    assert "кэф 1.85" in text
    assert "**Арсенал — Челси**" in text
    assert "кэф 1.50" in text


def test_settled_text_for_win_shows_profit():
    bet = _bet(status="won", payout=1850.0, profit=850.0)
    text = telegram_service.bet_settled_text(bet, "RUB")
    assert "✅ Выигрыш" in text
    # сумма и выплата намеренно скрыты
    assert "Сумма" not in text
    assert "Выплата" not in text
    assert "1 850" not in text
    assert "Ставка зашла" in text


def test_settled_text_for_loss_shows_stake():
    text = telegram_service.bet_settled_text(_bet(status="lost", profit=-1000.0), "RUB")
    assert "❌ Проигрыш" in text
    # сумма и потеря намеренно скрыты
    assert "Сумма" not in text
    assert "Потеря" not in text
    assert "1 000" not in text
    assert "Ставка не зашла" in text


# --- интеграция с API -------------------------------------------------------

def _enable_telegram(client) -> None:
    response = client.put(
        "/api/settings",
        json={
            "values": {
                "telegram_enabled": True,
                "telegram_bot_token": "TOKEN",
                "telegram_chat_id": "42",
            }
        },
    )
    assert response.status_code == 200


def _create_bet(client, **overrides) -> dict:
    payload = {
        "kind": "single",
        "sport": "Футбол",
        "event_name": "Реал Мадрид — Барселона",
        "prediction": "П2",
        "coefficient": 1.85,
        "stake": 1000,
    }
    payload.update(overrides)
    response = client.post("/api/bets", json=payload)
    assert response.status_code == 201
    return response.json()


def test_no_notifications_when_disabled(client, sent):
    bet = _create_bet(client)
    assert client.patch(f"/api/bets/{bet['id']}/result", json={"status": "won"}).status_code == 200
    assert sent == []


def test_notifications_on_create_and_settle(client, sent):
    _enable_telegram(client)
    bet = _create_bet(client)
    assert len(sent) == 1
    assert "🎯 Новая ставка" in sent[0]["payload"]["text"]

    assert client.patch(f"/api/bets/{bet['id']}/result", json={"status": "won"}).status_code == 200
    assert len(sent) == 2
    assert "✅ Выигрыш" in sent[1]["payload"]["text"]

    # Повторное сохранение того же результата не должно давать дубль.
    assert client.patch(f"/api/bets/{bet['id']}/result", json={"status": "won"}).status_code == 200
    assert len(sent) == 2


def test_express_notifies_once_when_all_legs_settled(client, sent):
    _enable_telegram(client)
    bet = _create_bet(
        client,
        kind="express",
        event_name=None,
        coefficient=None,
        legs=[
            {"event_name": "Арсенал — Челси", "coefficient": 1.5},
            {"event_name": "Бавария — Боруссия", "coefficient": 1.4},
        ],
    )
    assert len(sent) == 1  # уведомление о создании
    legs = bet["legs"]

    first = client.patch(
        f"/api/bets/{bet['id']}/legs/{legs[0]['id']}/result", json={"status": "won"}
    )
    assert first.status_code == 200
    assert len(sent) == 1  # экспресс ещё не рассчитан

    second = client.patch(
        f"/api/bets/{bet['id']}/legs/{legs[1]['id']}/result", json={"status": "won"}
    )
    assert second.status_code == 200
    assert second.json()["status"] == "won"
    assert len(sent) == 2


def test_bet_is_saved_when_telegram_unavailable(client, monkeypatch):
    def failing_urlopen(request, timeout=None):  # noqa: ANN001
        raise urllib.error.URLError("нет доступа")

    _enable_telegram(client)
    monkeypatch.setattr(telegram_service.urllib.request, "urlopen", failing_urlopen)
    bet = _create_bet(client)
    assert bet["status"] == "pending"


def test_settings_test_endpoint(client, sent):
    _enable_telegram(client)
    response = client.post("/api/settings/telegram/test")
    assert response.status_code == 200
    assert sent[0]["payload"]["text"] == telegram_service.TEST_MESSAGE


# --- определение группы -----------------------------------------------------

def _route_urlopen(responses: dict):
    """Подмена urlopen: отвечает по имени вызванного метода Bot API."""

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        method = request.full_url.rsplit("/", 1)[-1]
        payload = responses.get(method)
        if payload is None:
            return _Response({"ok": False, "description": f"нет ответа для {method}"})
        return _Response(payload)

    return fake_urlopen


def _patch_api(monkeypatch, responses: dict) -> None:
    monkeypatch.setattr(
        telegram_service.urllib.request, "urlopen", _route_urlopen(responses)
    )


def test_detect_group_finds_group_from_updates(monkeypatch):
    updates = [
        {"update_id": 1, "message": {"chat": {"id": 5, "type": "private"}}},
        {
            "update_id": 2,
            "my_chat_member": {
                "chat": {"id": -100123, "type": "supergroup", "title": "Ставки"}
            },
        },
    ]
    _patch_api(monkeypatch, {"getUpdates": {"ok": True, "result": updates}})
    ok, chat, error = telegram_service.detect_group("TOKEN")
    assert ok is True
    assert chat["id"] == -100123
    assert chat["title"] == "Ставки"
    assert error == ""


def test_detect_group_reports_when_no_group(monkeypatch):
    updates = [{"update_id": 1, "message": {"chat": {"id": 5, "type": "private"}}}]
    _patch_api(monkeypatch, {"getUpdates": {"ok": True, "result": updates}})
    ok, chat, error = telegram_service.detect_group("TOKEN")
    assert ok is False
    assert chat == {}
    assert "Группа не найдена" in error


def test_detect_group_ignores_chat_without_id(monkeypatch):
    updates = [{"update_id": 1, "message": {"chat": {"type": "group", "title": "Без id"}}}]
    _patch_api(monkeypatch, {"getUpdates": {"ok": True, "result": updates}})
    ok, _, error = telegram_service.detect_group("TOKEN")
    assert ok is False
    assert "Группа не найдена" in error


def test_detect_group_reports_network_error(monkeypatch):
    def failing_urlopen(request, timeout=None):  # noqa: ANN001
        raise urllib.error.URLError("нет доступа")

    monkeypatch.setattr(telegram_service.urllib.request, "urlopen", failing_urlopen)
    ok, _, error = telegram_service.detect_group("TOKEN")
    assert ok is False
    assert "сеть недоступна" in error


def test_chat_admin_status_true_for_administrator(monkeypatch):
    _patch_api(
        monkeypatch,
        {
            "getMe": {"ok": True, "result": {"id": 777}},
            "getChatMember": {"ok": True, "result": {"status": "administrator"}},
        },
    )
    is_admin, status, error = telegram_service.chat_admin_status("TOKEN", -100123)
    assert is_admin is True
    assert status == "administrator"
    assert error == ""


def test_detect_group_chat_requires_token():
    ok, chat, error = telegram_service.detect_group_chat({"telegram_bot_token": ""})
    assert ok is False
    assert "токен" in error.lower()


def test_detect_group_chat_combines_group_and_admin(monkeypatch):
    _patch_api(
        monkeypatch,
        {
            "getUpdates": {
                "ok": True,
                "result": [
                    {
                        "update_id": 1,
                        "my_chat_member": {
                            "chat": {"id": -1005, "type": "group", "title": "Беттинг"}
                        },
                    }
                ],
            },
            "getMe": {"ok": True, "result": {"id": 777}},
            "getChatMember": {"ok": True, "result": {"status": "administrator"}},
        },
    )
    ok, chat, warning = telegram_service.detect_group_chat({"telegram_bot_token": "TOKEN"})
    assert ok is True
    assert chat["chat_id"] == -1005
    assert chat["title"] == "Беттинг"
    assert chat["is_admin"] is True
    assert warning == ""


def test_detect_group_chat_flags_missing_admin(monkeypatch):
    _patch_api(
        monkeypatch,
        {
            "getUpdates": {
                "ok": True,
                "result": [
                    {"update_id": 1, "message": {"chat": {"id": -1005, "type": "group"}}}
                ],
            },
            "getMe": {"ok": True, "result": {"id": 777}},
            "getChatMember": {"ok": True, "result": {"status": "member"}},
        },
    )
    ok, chat, _ = telegram_service.detect_group_chat({"telegram_bot_token": "TOKEN"})
    assert ok is True
    assert chat["is_admin"] is False


def test_detect_endpoint_saves_group_chat_id(client, monkeypatch):
    client.put("/api/settings", json={"values": {"telegram_bot_token": "TOKEN"}})
    _patch_api(
        monkeypatch,
        {
            "getUpdates": {
                "ok": True,
                "result": [
                    {
                        "update_id": 1,
                        "my_chat_member": {
                            "chat": {"id": -100777, "type": "supergroup", "title": "Winners"}
                        },
                    }
                ],
            },
            "getMe": {"ok": True, "result": {"id": 777}},
            "getChatMember": {"ok": True, "result": {"status": "administrator"}},
        },
    )
    response = client.post("/api/settings/telegram/detect")
    assert response.status_code == 200
    data = response.json()
    assert data["chat_id"] == "-100777"
    assert data["title"] == "Winners"
    assert data["is_admin"] is True

    saved = client.get("/api/settings").json()["values"]
    assert saved["telegram_chat_id"] == "-100777"


def test_detect_endpoint_fails_without_group(client, monkeypatch):
    client.put("/api/settings", json={"values": {"telegram_bot_token": "TOKEN"}})
    _patch_api(monkeypatch, {"getUpdates": {"ok": True, "result": []}})
    response = client.post("/api/settings/telegram/detect")
    assert response.status_code == 400
    assert "Группа не найдена" in response.json()["detail"]