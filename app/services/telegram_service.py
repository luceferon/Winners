"""Уведомления о ставках в Telegram (Bot API).

Отправку выполняет сервер. Сообщение ставится в фоновые задачи запроса
(FastAPI ``BackgroundTasks``), поэтому недоступность Telegram не мешает
сохранить ставку и не увеличивает время ответа API.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.services import settings_service

logger = logging.getLogger("winners.telegram")

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT_SECONDS = 5.0
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1.0

CURRENCY_SIGNS = {"RUB": "₽", "USD": "$", "EUR": "€", "KZT": "₸"}

# Иконка и заголовок сообщения по рассчитанному статусу ставки.
STATUS_TITLES = {
    "won": ("✅", "Выигрыш"),
    "lost": ("❌", "Проигрыш"),
    "push": ("↩️", "Возврат"),
    "cancelled": ("🚫", "Отмена"),
}

TEST_MESSAGE = "🔔 Winners: тестовое сообщение. Уведомления настроены."


# --- форматирование ---------------------------------------------------------

def _money(value: Any, currency: str) -> str:
    """Сумма в принятом в интерфейсе виде: «1 850 ₽»."""
    number = abs(float(value or 0))
    text = f"{number:,.2f}".replace(",", " ").replace(".", ",")
    if text.endswith(",00"):
        text = text[:-3]
    sign = CURRENCY_SIGNS.get(currency, currency)
    return f"{text} {sign}".strip()


def _signed_money(value: Any, currency: str) -> str:
    number = float(value or 0)
    prefix = "+" if number > 0 else "−" if number < 0 else ""
    return f"{prefix}{_money(number, currency)}"


def _coefficient(value: Any) -> str:
    return f"{float(value or 0):.2f}"


def _bold(text: str) -> str:
    """Оборачивает текст в ** для жирного отображения."""
    return f"**{text}**" if text else text


def bet_created_text(bet: dict[str, Any], currency: str = "RUB") -> str:
    """Сообщение о новой ставке."""
    lines = []
    sport = bet.get("sport") or "без вида спорта"

    if bet.get("kind") == "express":
        legs = bet.get("legs") or []
        title = f"🎯 Новый экспресс ({len(legs)} событий) · {sport}"
        lines.append(title)
        # Для экспресса перечисляем каждое событие с прогнозом
        for leg in legs:
            event_name = leg.get("event_name") or ""
            coeff = leg.get("coefficient") or 0
            prediction = leg.get("prediction") or ""
            if prediction:
                lines.append(f"{_bold(event_name)} — {prediction}, кэф {_coefficient(coeff)}")
            else:
                lines.append(f"{_bold(event_name)} — кэф {_coefficient(coeff)}")
        # Общая сумма всех ставок в экспрессе
        total_stake = sum(leg.get("stake", 0) for leg in legs)
        if total_stake:
            lines.append(f"Сумма {_money(total_stake, currency)}")
    else:
        title = f"🎯 Новая ставка · {sport}"
        lines = [title, _bold(str(bet.get("event_name") or ""))]

        if bet.get("prediction"):
            lines.append(f"Прогноз: {bet['prediction']}")

        lines.append(
            f"Кэф {_coefficient(bet.get('coefficient'))} · "
            f"Сумма {_money(bet.get('stake'), currency)}"
        )

        if bet.get("potential_payout"):
            lines.append(f"Возможная выплата: {_money(bet.get('potential_payout'), currency)}")

        if bet.get("comment"):
            lines.append(f"Комментарий: {bet['comment']}")

    return "\n".join(line for line in lines if line)


def bet_settled_text(bet: dict[str, Any], currency: str = "RUB") -> str:
    """Сообщение о рассчитанной ставке («зашла или нет»)."""
    status = str(bet.get("status") or "")
    icon, title = STATUS_TITLES.get(status, ("ℹ️", status))
    lines = [
        f"{icon} {title} · {_bold(str(bet.get('sport') or 'без вида спорта'))}",
        _bold(str(bet.get("event_name") or "")),
        f"Кэф {_coefficient(bet.get('coefficient'))} · "
        f"Сумма {_money(bet.get('stake'), currency)}",
    ]
    if status == "won":
        lines.append(
            f"Выплата: {_money(bet.get('payout'), currency)} "
            f"({_signed_money(bet.get('profit'), currency)})"
        )
    elif status == "lost":
        lines.append(f"Потеря: {_money(bet.get('stake'), currency)}")
    elif status == "push":
        lines.append(f"Возврат суммы ставки: {_money(bet.get('stake'), currency)}")
    else:
        lines.append("Ставка отменена, сумма возвращена")
    return "\n".join(line for line in lines if line)


# --- отправка ---------------------------------------------------------------

def _post(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """Отправить сообщение через Bot API. Возвращает (успех, текст ошибки)."""
    payload = json.dumps(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    ).encode("utf-8")
    request = urllib.request.Request(
        API_URL.format(token=token),
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", "replace")).get("description")
        except Exception:  # тело ответа может быть не JSON
            detail = None
        return False, str(detail or f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError) as exc:
        return False, f"сеть недоступна ({exc})"

    try:
        data = json.loads(body)
    except ValueError:
        return False, "некорректный ответ Telegram"
    if not data.get("ok"):
        return False, str(data.get("description") or "Telegram отклонил запрос")
    return True, ""


def send_message(text: str, token: str, chat_id: str) -> bool:
    """Отправить сообщение с повторными попытками (до 3 раз)."""
    last_error = ""
    for attempt in range(1, MAX_RETRIES + 1):
        ok, error = _post(token, chat_id, text)
        if ok:
            if attempt > 1:
                logger.info("Уведомление в Telegram отправлено с попытки %d", attempt)
            return True
        last_error = error
        if attempt < MAX_RETRIES:
            logger.warning(
                "Попытка %d/%d отправки в Telegram не удалась: %s. Повтор через %.1f с...",
                attempt,
                MAX_RETRIES,
                error,
                RETRY_DELAY_SECONDS,
            )
            time.sleep(RETRY_DELAY_SECONDS)
    logger.warning(
        "Уведомление в Telegram не отправлено после %d попыток: %s",
        MAX_RETRIES,
        last_error,
    )
    return False


def send_test_message(settings: dict[str, Any]) -> tuple[bool, str]:
    """Проверка настроек: отправляет тестовое сообщение прямо из запроса."""
    token = str(settings.get("telegram_bot_token") or "").strip()
    chat_id = str(settings.get("telegram_chat_id") or "").strip()
    if not token or not chat_id:
        return False, "Укажите токен бота и ID чата"
    return _post(token, chat_id, TEST_MESSAGE)


def queue_bet_notification(
    background: BackgroundTasks,
    db: Session,
    bet: dict[str, Any],
    *,
    event: str,
) -> None:
    """Поставить уведомление о ставке в фоновые задачи запроса.

    ``event`` — ``created`` (новая ставка) или ``settled`` (расчёт).
    """
    if event not in {"created", "settled"}:
        raise ValueError(f"Неизвестное событие уведомления: {event}")

    settings = settings_service.get_settings(db)
    if not settings.get("telegram_enabled"):
        return
    flag = "telegram_notify_on_create" if event == "created" else "telegram_notify_on_settle"
    if not settings.get(flag, True):
        return

    token = str(settings.get("telegram_bot_token") or "").strip()
    chat_id = str(settings.get("telegram_chat_id") or "").strip()
    if not token or not chat_id:
        logger.warning("Уведомления Telegram включены, но токен или ID чата не заданы")
        return

    currency = str(settings.get("currency") or "RUB")
    text = bet_created_text(bet, currency) if event == "created" else bet_settled_text(bet, currency)
    if text:
        background.add_task(send_message, text, token, chat_id)