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
import uuid
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.services import settings_service

logger = logging.getLogger("winners.telegram")

API_BASE = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT_SECONDS = 5.0
MAX_RETRIES = 10
RETRY_DELAY_SECONDS = 1.0

# Типы чатов, которые считаются группой, и статусы участника-администратора.
GROUP_CHAT_TYPES = {"group", "supergroup"}
ADMIN_STATUSES = {"administrator", "creator"}

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
    """Сообщение о новой ставке.

    Финансовые данные (сумма, возможная выплата) намеренно не включаются —
    чтобы не светить суммы в Telegram. Остаются событие, прогноз и
    коэффициент.
    """
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
    else:
        title = f"🎯 Новая ставка · {sport}"
        lines = [title, _bold(str(bet.get("event_name") or ""))]

        if bet.get("prediction"):
            lines.append(f"Прогноз: {bet['prediction']}")

        lines.append(f"Кэф {_coefficient(bet.get('coefficient'))}")

        if bet.get("comment"):
            lines.append(f"Комментарий: {bet['comment']}")

    return "\n".join(line for line in lines if line)


def bet_settled_text(bet: dict[str, Any], currency: str = "RUB") -> str:
    """Сообщение о рассчитанной ставке («зашла или нет»).

    Финансовые данные (сумма, выплата, прибыль) намеренно не включаются —
    чтобы не светить суммы в Telegram. Остаются статус, вид спорта, событие
    и коэффициент.
    """
    status = str(bet.get("status") or "")
    icon, title = STATUS_TITLES.get(status, ("ℹ️", status))
    lines = [
        f"{icon} {title} · {_bold(str(bet.get('sport') or 'без вида спорта'))}",
        _bold(str(bet.get("event_name") or "")),
        f"Кэф {_coefficient(bet.get('coefficient'))}",
    ]
    if status == "won":
        lines.append("Ставка зашла")
    elif status == "lost":
        lines.append("Ставка не зашла")
    elif status == "push":
        lines.append("Возврат")
    else:
        lines.append("Ставка отменена")
    return "\n".join(line for line in lines if line)


# --- вызовы Bot API ---------------------------------------------------------

def _api_call(
    token: str,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float = TIMEOUT_SECONDS,
) -> tuple[bool, Any, str]:
    """Вызвать метод Bot API. Возвращает (успех, результат, текст ошибки)."""
    payload = json.dumps(params or {}).encode("utf-8")
    request = urllib.request.Request(
        API_BASE.format(token=token, method=method),
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", "replace")).get("description")
        except Exception:  # тело ответа может быть не JSON
            detail = None
        return False, None, str(detail or f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError) as exc:
        return False, None, f"сеть недоступна ({exc})"

    try:
        data = json.loads(body)
    except ValueError:
        return False, None, "некорректный ответ Telegram"
    if not data.get("ok"):
        return False, None, str(data.get("description") or "Telegram отклонил запрос")
    return True, data.get("result"), ""


def _post(
    token: str,
    chat_id: str,
    text: str,
    *,
    reply_to_message_id: int | None = None,
) -> tuple[bool, int | None, str]:
    """Отправить сообщение через Bot API.

    Возвращает (успех, message_id или None, текст ошибки).
    """
    params: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_to_message_id is not None:
        params["reply_to_message_id"] = reply_to_message_id
    ok, result, error = _api_call(token, "sendMessage", params)
    message_id = (
        int(result.get("message_id"))
        if ok and isinstance(result, dict) and result.get("message_id")
        else None
    )
    return ok, message_id, error


def send_message(
    text: str,
    token: str,
    chat_id: str,
    *,
    reply_to_message_id: int | None = None,
) -> int | None:
    """Отправить сообщение с повторными попытками (до 3 раз).

    Возвращает ``message_id`` отправленного сообщения или ``None`` при неудаче.
    """
    last_error = ""
    for attempt in range(1, MAX_RETRIES + 1):
        ok, message_id, error = _post(
            token, chat_id, text, reply_to_message_id=reply_to_message_id
        )
        if ok:
            if attempt > 1:
                logger.info("Уведомление в Telegram отправлено с попытки %d", attempt)
            return message_id
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
    return None


def send_photo(
    token: str,
    chat_id: str,
    photo_bytes: bytes,
    caption: str = "",
    *,
    reply_to_message_id: int | None = None,
) -> tuple[bool, int | None, str]:
    """Отправить фото через ``sendPhoto`` (multipart/form-data).

    Возвращает (успех, message_id или None, текст ошибки). Используется для
    отправки скриншота ставки с замазанной суммой (тестовая фича).
    """
    boundary = f"----Winners{uuid.uuid4().hex}"
    lines: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        lines.append(f"--{boundary}\r\n".encode("utf-8"))
        lines.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        )
        lines.append(value.encode("utf-8"))
        lines.append(b"\r\n")

    add_field("chat_id", str(chat_id))
    if caption:
        add_field("caption", caption)
    if reply_to_message_id is not None:
        add_field("reply_to_message_id", str(reply_to_message_id))

    lines.append(f"--{boundary}\r\n".encode("utf-8"))
    lines.append(
        b'Content-Disposition: form-data; name="photo"; filename="bet.png"\r\n'
    )
    lines.append(b"Content-Type: image/png\r\n\r\n")
    lines.append(photo_bytes)
    lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode("utf-8"))

    body = b"".join(lines)
    request = urllib.request.Request(
        API_BASE.format(token=token, method="sendPhoto"),
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", "replace")).get("description")
        except Exception:
            detail = None
        return False, None, str(detail or f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError) as exc:
        return False, None, f"сеть недоступна ({exc})"
    except ValueError:
        return False, None, "некорректный ответ Telegram"

    if not data.get("ok"):
        return False, None, str(data.get("description") or "Telegram отклонил запрос")
    result = data.get("result")
    message_id = (
        int(result.get("message_id"))
        if isinstance(result, dict) and result.get("message_id")
        else None
    )
    return True, message_id, ""


def send_test_message(settings: dict[str, Any]) -> tuple[bool, str]:
    """Проверка настроек: отправляет тестовое сообщение прямо из запроса."""
    token = str(settings.get("telegram_bot_token") or "").strip()
    chat_id = str(settings.get("telegram_chat_id") or "").strip()
    if not token or not chat_id:
        return False, "Укажите токен бота и ID чата"
    ok, _, error = _post(token, chat_id, TEST_MESSAGE)
    return ok, error


# --- определение группы -----------------------------------------------------

def _group_chat_from_update(update: dict[str, Any]) -> dict[str, Any] | None:
    """Вернуть чат-группу из одного обновления Telegram или None."""
    for key in ("message", "edited_message", "channel_post", "my_chat_member"):
        payload = update.get(key)
        if not isinstance(payload, dict):
            continue
        chat = payload.get("chat")
        if (
            isinstance(chat, dict)
            and chat.get("type") in GROUP_CHAT_TYPES
            and chat.get("id") is not None
        ):
            return chat
    return None


def detect_group(token: str) -> tuple[bool, dict[str, Any], str]:
    """Найти через ``getUpdates`` группу, в которую добавлен бот.

    Возвращает (успех, чат, текст ошибки). Обновления не подтверждаются
    (offset не передаётся), поэтому вызов можно повторять безопасно.
    """
    ok, updates, error = _api_call(token, "getUpdates", {"limit": 100})
    if not ok:
        return False, {}, error

    for update in reversed(updates or []):
        if isinstance(update, dict):
            chat = _group_chat_from_update(update)
            if chat:
                return True, chat, ""
    return False, {}, (
        "Группа не найдена. Добавьте бота в группу, назначьте его администратором "
        "и отправьте сообщение в группе, затем повторите."
    )


def chat_admin_status(token: str, chat_id: Any) -> tuple[bool, str, str]:
    """Проверить, что бот — администратор чата.

    Возвращает (администратор, статус, текст ошибки).
    """
    ok, me, error = _api_call(token, "getMe")
    if not ok:
        return False, "", error
    bot_id = (me or {}).get("id")
    if not bot_id:
        return False, "", "не удалось определить бота (getMe)"

    ok, member, error = _api_call(
        token, "getChatMember", {"chat_id": chat_id, "user_id": bot_id}
    )
    if not ok:
        return False, "", error
    status = str((member or {}).get("status") or "")
    return status in ADMIN_STATUSES, status, ""


def detect_group_chat(settings: dict[str, Any]) -> tuple[bool, dict[str, Any], str]:
    """Определить группу бота и проверить права администратора.

    Возвращает (успех, сведения, текст ошибки). При успехе ``сведения``
    содержат ``chat_id``, ``title``, ``is_admin``, ``status``,
    а третий элемент — необязательное предупреждение о проверке прав.
    """
    token = str(settings.get("telegram_bot_token") or "").strip()
    if not token:
        return False, {}, "Укажите токен бота"

    ok, chat, error = detect_group(token)
    if not ok:
        return False, {}, error

    chat_id = chat.get("id")
    is_admin, status, admin_error = chat_admin_status(token, chat_id)
    result = {
        "chat_id": chat_id,
        "title": str(chat.get("title") or ""),
        "is_admin": is_admin,
        "status": status,
    }
    warning = f"Не удалось проверить права: {admin_error}" if admin_error else ""
    return True, result, warning


def _store_message_id(bet_id: int, message_id: int) -> None:
    """Сохранить ID сообщения Telegram в ставке (отдельная сессия БД)."""
    from app.database import SessionLocal
    from app.models import Bet

    try:
        with SessionLocal() as db:
            bet = db.get(Bet, bet_id)
            if bet is not None:
                bet.telegram_message_id = message_id
                db.commit()
    except Exception:
        logger.exception("Не удалось сохранить telegram_message_id для ставки #%d", bet_id)


def _send_created_and_store(
    bet_id: int,
    token: str,
    chat_id: str,
    text: str,
    photo: bytes | None,
    send_screenshot: bool,
) -> None:
    """Фоновая задача: отправить уведомление о создании и сохранить message_id."""
    message_id: int | None = None
    if photo and send_screenshot:
        caption = text
        if len(caption) > 1024:
            caption = caption[:1021] + "..."
        ok, message_id, _ = send_photo(token, chat_id, photo, caption)
        if not ok:
            # Если фото не отправилось — пробуем обычное сообщение.
            message_id = send_message(text, token, chat_id)
    else:
        message_id = send_message(text, token, chat_id)

    if message_id is not None:
        _store_message_id(bet_id, message_id)


def _send_settled_reply(
    token: str,
    chat_id: str,
    text: str,
    reply_to_message_id: int | None,
) -> None:
    """Фоновая задача: отправить уведомление о расчёте (ответом на создание)."""
    send_message(text, token, chat_id, reply_to_message_id=reply_to_message_id)


def queue_bet_notification(
    background: BackgroundTasks,
    db: Session,
    bet: dict[str, Any],
    *,
    event: str,
    photo: bytes | None = None,
) -> None:
    """Поставить уведомление о ставке в фоновые задачи запроса.

    ``event`` — ``created`` (новая ставка) или ``settled`` (расчёт).
    ``photo`` — опциональный скриншот ставки (PNG) для ``sendPhoto``
    (тестовая фича: отправляется, если включена настройка
    ``telegram_send_screenshot``).

    При создании ставки сохраняется ``message_id`` отправленного сообщения,
    чтобы при расчёте уведомление пришло **ответом** на исходное сообщение.
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

    bet_id = bet.get("id")
    if event == "created":
        background.add_task(
            _send_created_and_store,
            bet_id,
            token,
            chat_id,
            text,
            photo,
            bool(settings.get("telegram_send_screenshot")),
        )
    else:
        reply_to = bet.get("telegram_message_id")
        background.add_task(_send_settled_reply, token, chat_id, text, reply_to)