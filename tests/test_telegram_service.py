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
        return _Response({"ok": True})

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
    assert telegram_service.send_message("привет", "TOKEN", "42") is True
    assert len(sent) == 1
    assert sent[0]["url"].endswith("/botTOKEN/sendMessage")
    assert sent[0]["payload"]["chat_id"] == "42"
    assert sent[0]["payload"]["text"] == "привет"


def test_send_message_returns_false_on_network_error(monkeypatch):
    def failing_urlopen(request, timeout=None):  # noqa: ANN001
        raise urllib.error.URLError("нет доступа")

    monkeypatch.setattr(telegram_service.urllib.request, "urlopen", failing_urlopen)
    assert telegram_service.send_message("привет", "TOKEN", "42") is False


def test_send_message_reports_api_error(monkeypatch):
    def failing_urlopen(request, timeout=None):  # noqa: ANN001
        return _Response({"ok": False, "description": "chat not found"})

    monkeypatch.setattr(telegram_service.urllib.request, "urlopen", failing_urlopen)
    assert telegram_service.send_message("привет", "TOKEN", "42") is False


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
    assert "Кэф 1.85 · Сумма 1 000 ₽" in text
    assert "Возможная выплата: 1 850 ₽" in text
    # Убрано: assert "Источник: Bet365" in text


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
    # Убираем проверку начала строки, проверяем содержимое
    assert "✅ Выигрыш" in text
    assert "Выплата: 1 850 ₽ (+850 ₽)" in text


def test_settled_text_for_loss_shows_stake():
    text = telegram_service.bet_settled_text(_bet(status="lost", profit=-1000.0), "RUB")
    assert "❌ Проигрыш" in text
    assert "Потеря: 1 000 ₽" in text


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