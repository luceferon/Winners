"""Распознавание ставки со скриншота: буфер обмена, OCR и разбор текста.

Распознавание выполняется встроенным в Windows движком ``Windows.Media.Ocr``:
он работает офлайн, не требует внешних моделей и установки Tesseract.
Из распознанного текста извлекаются название события, прогноз, коэффициент
и сумма ставки.
"""

from __future__ import annotations

import asyncio
import io
import re
from pathlib import Path
from typing import Any, NamedTuple


# --- ошибки -----------------------------------------------------------------
class OcrError(RuntimeError):
    """Не удалось получить или распознать изображение."""


class OcrUnavailableError(OcrError):
    """Движок распознавания недоступен: нет Windows OCR или языкового пакета."""


# --- настройки --------------------------------------------------------------
# Мелкие скриншоты Windows OCR читает неточно: увеличиваем их перед распознаванием.
UPSCALE_FACTOR = 3.0
UPSCALE_MIN_WIDTH = 1500

# Порог бинаризации для повторного прохода: иногда он сохраняет десятичную точку,
# которую обычный проход теряет («200.00» -> «20000»).
BINARIZE_THRESHOLD = 180

# Языковые теги в порядке предпочтения (русский — для скриншотов БК).
LANGUAGE_TAGS = ("ru", "en-US")

COEFFICIENT_MIN = 1.01
COEFFICIENT_MAX = 1000.0

# Доля межстрочного интервала, в пределах которой строка коэффициента считается
# стоящей на одной высоте со строкой прогноза своей ноги.
COEFFICIENT_ROW_TOLERANCE_RATIO = 0.6
COEFFICIENT_ROW_TOLERANCE_DEFAULT = 120.0

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}

# --- шаблоны разбора --------------------------------------------------------
_DECIMAL_RE = re.compile(r"(?<![\d.,])(\d{1,4}[.,]\d{1,3})(?![\d])")
# Число: пробел считается разделителем тысяч только в группе ровно из трёх цифр,
# иначе (например, «200 00» — точка, прочитанная как пробел) цифры не склеиваются.
_NUMBER_RE = re.compile(r"\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?")
# Строка из одного числа (возможно, с валютой) — значение суммы на отдельной строке.
_PLAIN_NUMBER_RE = re.compile(
    r"(\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?)\s*(?:₽|руб\.?|р\.?)?", re.I
)
_PAREN_RE = re.compile(r"\([^)]*\)")
# Дата или время — такие числа нельзя принимать за коэффициент.
_DATE_RE = re.compile(
    r"\d{1,2}\.\d{1,2}\.\d{2,4}"            # 25.11.2025
    r"|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?"  # 25/11, 25-11-2025
    r"|\d{1,2}:\d{2}"                       # 22:18
)
# Название события — два слова, разделённые тире (с пробелами или без).
_EVENT_RE = re.compile(r"[^\W\d_]{2,}\s*[-—–]\s*[^\W\d_]{2,}", re.UNICODE)
_EXPRESS_RE = re.compile(r"экспресс", re.I)
_STAKE_RE = re.compile(r"ставк|сумм|руб", re.I)
_COEF_RE = re.compile(r"(?:кф|коэф\w*|kf)\s*[:№]?\s*(\d{1,4}[.,]\d{1,3})", re.I)
_PREDICTION_RE = re.compile(
    r"период|больше|меньше|тотал|фора|исход|побед|ничья|партия"
    r"|\bтб\b|\bтм\b|\bп1\b|\bп2\b|\b1x\b|\bx2\b|\b12\b",
    re.I,
)
# Счёт матча («1:4», «0:2», «1:0 33'») — строка между событием и прогнозом,
# её нужно пропускать при сборке ног экспресса.
_SCORE_RE = re.compile(r"\b\d{1,2}:\d{1,2}\b")


# --- чтение буфера обмена ---------------------------------------------------
def _image_to_png(image: Any) -> bytes:
    """Сохранить PIL-изображение в PNG-байты."""
    if getattr(image, "mode", "") not in ("RGB", "L"):
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def read_clipboard_image() -> bytes | None:
    """Вернуть PNG-байты картинки из буфера обмена. ``None`` — картинки нет."""
    try:
        from PIL import ImageGrab
    except Exception as exc:  # pragma: no cover - зависит от окружения
        raise OcrUnavailableError("Модуль Pillow недоступен для чтения буфера обмена") from exc

    try:
        grabbed = ImageGrab.grabclipboard()
    except Exception as exc:
        raise OcrError("Не удалось прочитать буфер обмена") from exc

    if grabbed is None:
        return None
    if isinstance(grabbed, list):
        # В буфере лежит файл (CF_HDROP) — берём первое изображение из списка.
        for name in grabbed:
            path = Path(str(name))
            if path.suffix.lower() in IMAGE_SUFFIXES and path.is_file():
                try:
                    return path.read_bytes()
                except OSError as exc:
                    raise OcrError(
                        "Не удалось прочитать файл изображения из буфера обмена"
                    ) from exc
        return None
    return _image_to_png(grabbed)


# --- распознавание ----------------------------------------------------------
def _binarize(image: Any) -> Any:
    """Привести изображение к двум тонам: тёмный текст на светлом фоне."""
    gray = image.convert("L")
    return gray.point(lambda pixel: 0 if pixel < BINARIZE_THRESHOLD else 255)


def _prepare_image(data: bytes, binarize: bool = False) -> Any:
    """Открыть изображение и увеличить мелкое для точности OCR."""
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - зависит от окружения
        raise OcrUnavailableError("Модуль Pillow недоступен") from exc

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        raise OcrError("Не удалось прочитать изображение") from exc

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    if image.width and image.width < UPSCALE_MIN_WIDTH:
        size = (
            int(image.width * UPSCALE_FACTOR),
            int(image.height * UPSCALE_FACTOR),
        )
        image = image.resize(size, Image.Resampling.LANCZOS)
    if binarize:
        image = _binarize(image)
    return image


def _pick_engine(ocr_engine_cls: Any) -> Any:
    """Первый доступный движок OCR: сначала русский, затем английский."""
    from winrt.windows.globalization import Language

    for tag in LANGUAGE_TAGS:
        try:
            engine = ocr_engine_cls.try_create_from_language(Language(tag))
        except Exception:
            engine = None
        if engine is not None:
            return engine
    try:
        return ocr_engine_cls.try_create_from_user_profile_languages()
    except Exception:  # pragma: no cover - зависит от окружения
        return None


class OcrLine(NamedTuple):
    """Строка OCR вместе с её положением на изображении."""

    text: str
    x: float
    y: float
    right: float
    bottom: float


async def _recognize_async(png_bytes: bytes) -> list[OcrLine]:
    try:
        from winrt.windows.graphics.imaging import (
            BitmapAlphaMode,
            BitmapDecoder,
            BitmapPixelFormat,
        )
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    except Exception as exc:
        raise OcrUnavailableError(
            "Windows OCR недоступен: не установлены пакеты winrt"
        ) from exc

    engine = _pick_engine(OcrEngine)
    if engine is None:
        raise OcrUnavailableError(
            "Windows OCR недоступен: не найден языковой пакет распознавания"
        )

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png_bytes)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)

    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async(
        BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED
    )
    result = await engine.recognize_async(bitmap)

    lines: list[OcrLine] = []
    for line in result.lines:
        text = (getattr(line, "text", "") or "").strip()
        if not text:
            continue
        words = [word for word in getattr(line, "words", []) if word]
        if words:
            left = min(word.bounding_rect.x for word in words)
            top = min(word.bounding_rect.y for word in words)
            right = max(word.bounding_rect.x + word.bounding_rect.width for word in words)
            bottom = max(word.bounding_rect.y + word.bounding_rect.height for word in words)
        else:
            left = top = right = bottom = 0.0
        lines.append(OcrLine(text, float(left), float(top), float(right), float(bottom)))
    if not lines and result.text:
        lines.append(OcrLine(result.text.strip(), 0.0, 0.0, 0.0, 0.0))
    return lines


def _run(coro: Any) -> Any:
    """Выполнить корутину WinRT, даже если уже есть активный цикл событий."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:  # pragma: no cover
        return pool.submit(asyncio.run, coro).result()


def recognize_lines(data: bytes, binarize: bool = False) -> list[OcrLine]:
    """Распознать строки изображения вместе с их координатами.

    Координаты нужны, чтобы привязать коэффициент к событию экспресса по высоте
    строки, а не по порядку строк в тексте (он у OCR не гарантирован).
    """
    if not data:
        raise OcrError("Пустое изображение")
    image = _prepare_image(data, binarize=binarize)
    return _run(_recognize_async(_image_to_png(image)))


def _lines_to_text(lines: list[OcrLine]) -> str:
    return "\n".join(line.text for line in lines if line.text).strip()


def recognize_image(data: bytes, binarize: bool = False) -> str:
    """Распознать текст на изображении (Windows OCR).

    ``binarize=True`` включает бинаризацию: она помогает удержать десятичную точку.
    """
    return _lines_to_text(recognize_lines(data, binarize=binarize))


# --- разбор текста ----------------------------------------------------------
def _clean_lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _to_float(token: str) -> float | None:
    try:
        return float(token.replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _stake_candidates(lines: list[str]):
    """Суммы в порядке появления: ``(индексы строк, числовой токен)``.

    Значение может стоять в строке-метке («Ставка 100.00») или на следующей строке
    («Ставка» / «100.00»).
    """
    for index, line in enumerate(lines):
        if not _STAKE_RE.search(line):
            continue
        match = _NUMBER_RE.search(line)
        if match:
            yield {index}, match.group(0)
            continue
        neighbor = index + 1
        if neighbor < len(lines):
            token = _PLAIN_NUMBER_RE.fullmatch(lines[neighbor].strip())
            if token:
                yield {index, neighbor}, token.group(1)


def _find_stake(lines: list[str]) -> tuple[float | None, set[int]]:
    for used, number in _stake_candidates(lines):
        value = _to_float(number)
        if value and value > 0:
            return value, used
    return None, set()


def _stake_has_decimal(text: str) -> bool:
    """Есть ли у найденной суммы десятичный разделитель («Ставка 200.00»)."""
    for _, number in _stake_candidates(_clean_lines(text)):
        if _to_float(number):
            return bool(re.search(r"[.,]", number))
    return False


def _find_prediction(lines: list[str], skip: set[int]) -> tuple[str | None, set[int]]:
    for index, line in enumerate(lines):
        if index in skip:
            continue
        if _PREDICTION_RE.search(line):
            return line, {index}
    return None, set()


def _find_event(lines: list[str], skip: set[int]) -> tuple[str | None, set[int]]:
    for index, line in enumerate(lines):
        if index in skip:
            continue
        if _is_event_line(line):
            return line, {index}
    return None, set()


def _is_event_line(line: str) -> bool:
    """Похожа ли строка на название события «команда - команда».

    Первое слово слева от тире и первое слово справа должны начинаться
    с заглавной буквы: команды пишутся с большой буквы, а прогнозы вроде
    «Обе забьют - да» — нет (справа «да» строчная).
    """
    if not _EVENT_RE.search(line):
        return False
    parts = re.split(r"\s*[-—–]\s*", line, maxsplit=1)
    if len(parts) != 2:
        return False
    left = parts[0].strip().split()
    right = parts[1].strip().split()
    if not left or not right:
        return False
    return left[0][0].isupper() and right[0][0].isupper()


def _find_coefficient(
    lines: list[str], skip: set[int], stake: float | None = None
) -> float | None:
    # 1) Явная подпись «кф»/«коэффициент» — самый надёжный вариант.
    for index, line in enumerate(lines):
        if index in skip:
            continue
        match = _COEF_RE.search(line)
        if match:
            value = _to_float(match.group(1))
            if value is not None and COEFFICIENT_MIN <= value <= COEFFICIENT_MAX:
                return value

    # 2) Иначе — первое отдельно стоящее число с дробной частью в нужном диапазоне,
    #    пропуская дату/время и уже найденную сумму ставки.
    for index, line in enumerate(lines):
        if index in skip:
            continue
        if _DATE_RE.search(line):
            continue
        cleaned = _PAREN_RE.sub(" ", line)
        for match in _DECIMAL_RE.finditer(cleaned):
            value = _to_float(match.group(1))
            if value is None:
                continue
            if stake is not None and abs(value - stake) < 1e-9:
                continue
            if COEFFICIENT_MIN <= value <= COEFFICIENT_MAX:
                return value
    return None


def parse_bet_text(text: str) -> dict[str, Any]:
    """Извлечь из распознанного текста поля ставки.

    Сначала определяются «поглощающие» строки (сумма, прогноз, событие),
    чтобы они не были ошибочно приняты за коэффициент.
    """
    lines = _clean_lines(text)
    if not lines:
        return {"event_name": None, "prediction": None, "coefficient": None, "stake": None}

    skip: set[int] = set()

    stake, stake_lines = _find_stake(lines)
    skip |= stake_lines

    prediction, prediction_lines = _find_prediction(lines, skip)
    skip |= prediction_lines

    event_name, event_lines = _find_event(lines, skip)
    skip |= event_lines

    coefficient = _find_coefficient(lines, skip, stake)

    return {
        "event_name": event_name,
        "prediction": prediction,
        "coefficient": coefficient,
        "stake": stake,
    }


def _express_header_index(lines: list[str]) -> int:
    """Индекс строки-заголовка «Экспресс …» или ``-1``, если это не экспресс."""
    for index, line in enumerate(lines[:2]):
        if _EXPRESS_RE.search(line):
            return index
    return -1


def _legs_block_range(lines: list[str], start: int) -> tuple[int, int]:
    """Границы блока событий экспресса: от ``start`` до строки со суммой ставки."""
    for index in range(start, len(lines)):
        if _STAKE_RE.search(lines[index]):
            return start, index
    return start, len(lines)


def _is_score_line(line: str) -> bool:
    """Строка со счётом матча («1:4 (0:2, 1:2) П», «1:0 33'»).

    Такая строка стоит между событием и прогнозом и не должна попадать
    ни в название события, ни в прогноз.
    """
    return bool(_SCORE_RE.search(line)) and not _PREDICTION_RE.search(line)


def _collect_leg_pairs(lines: list[str], start: int, end: int) -> list[tuple[int, int]]:
    """Пары (индекс события, индекс прогноза) в блоке ног экспресса.

    Событие определяется по шаблону «команда - команда», прогноз — первая
    строка после события, не являющаяся счётом. Это поддерживает как ноги
    из двух строк (событие + прогноз), так и из трёх (событие + счёт + прогноз).
    """
    event_indices = [i for i in range(start, end) if _is_event_line(lines[i])]
    pairs: list[tuple[int, int]] = []
    for ei in event_indices:
        pi = ei + 1
        while pi < end and _is_score_line(lines[pi]):
            pi += 1
        if pi < end:
            pairs.append((ei, pi))
    return pairs


def _collect_coefficients(lines: list[str], start: int, stake: float | None) -> list[float]:
    """Числа-коэффициенты после строки со ставкой: общий и по событиям."""
    values: list[float] = []
    for index in range(start, len(lines)):
        line = lines[index]
        if _DATE_RE.search(line):
            continue
        token = _PLAIN_NUMBER_RE.fullmatch(line)
        if not token:
            continue
        value = _to_float(token.group(1))
        if value is None or not (COEFFICIENT_MIN <= value <= COEFFICIENT_MAX):
            continue
        if stake is not None and abs(value - stake) < 1e-9:
            continue
        values.append(value)
    return values


def _spread_coefficients(values: list[float], count: int) -> list[float | None]:
    """Разложить коэффициенты по событиям, досчитав единственный недостающий.

    Общий коэффициент экспресса больше коэффициента любого события, поэтому за
    общий принимается максимум. Если не найден ровно один коэффициент события,
    он вычисляется как «общий ÷ произведение остальных».
    """
    if count <= 0:
        return []
    coefficients = list(values)
    total = max(coefficients) if coefficients else None
    if total is not None:
        coefficients.remove(total)
    if len(coefficients) >= count:
        return coefficients[:count]
    if total is not None and count - len(coefficients) == 1 and coefficients:
        product = 1.0
        for value in coefficients:
            product *= value
        if product > 0:
            coefficients.append(round(total / product, 2))
    coefficients += [None] * (count - len(coefficients))
    return coefficients


def parse_express_text(text: str) -> dict[str, Any] | None:
    """Разобрать скриншот экспресса. ``None`` — текст не похож на экспресс.

    На скриншоте каждая нога занимает две строки (событие, затем прогноз),
    а коэффициенты идут числовым хвостом после суммы ставки: сначала общий,
    затем по событиям. Отсутствующий коэффициент одного события досчитывается
    из общего.
    """
    lines = _clean_lines(text)
    header = _express_header_index(lines)
    if header < 0:
        return None

    stake, stake_lines = _find_stake(lines)

    start, end = _legs_block_range(lines, header + 1)
    pairs = _collect_leg_pairs(lines, start, end)
    legs: list[dict[str, Any]] = [
        {
            "event_name": lines[ei] or None,
            "prediction": lines[pi] or None,
            "coefficient": None,
        }
        for ei, pi in pairs
    ]
    if len(legs) < 2:
        return None

    coef_start = max(stake_lines) + 1 if stake_lines else len(lines)
    values = _collect_coefficients(lines, coef_start, stake)
    for leg, coefficient in zip(legs, _spread_coefficients(values, len(legs))):
        leg["coefficient"] = coefficient

    return {
        "kind": "express",
        "event_name": None,
        "prediction": None,
        "coefficient": None,
        "stake": stake,
        "legs": legs,
    }


def _row_tolerance(predictions: list[float]) -> float:
    """Допуск привязки по высоте: доля межстрочного интервала между ногами."""
    if len(predictions) >= 2:
        ordered = sorted(predictions)
        gaps = sorted(b - a for a, b in zip(ordered, ordered[1:]) if b > a)
        if gaps:
            return max(gaps[len(gaps) // 2] * COEFFICIENT_ROW_TOLERANCE_RATIO, 1.0)
    return COEFFICIENT_ROW_TOLERANCE_DEFAULT


def _bind_coefficients(
    rows: list[tuple[float, float]], predictions: list[float]
) -> list[float | None]:
    """Связать коэффициенты со строками прогнозов по высоте (y)."""
    tolerance = _row_tolerance(predictions)
    result: list[float | None] = [None] * len(predictions)
    taken: set[int] = set()
    for y, value in sorted(rows):
        best, best_distance = -1, None
        for index, prediction_y in enumerate(predictions):
            if index in taken:
                continue
            distance = abs(prediction_y - y)
            if best_distance is None or distance < best_distance:
                best, best_distance = index, distance
        if best >= 0 and best_distance is not None and best_distance <= tolerance:
            result[best] = value
            taken.add(best)
    return result


def _coefficient_rows(
    boxes: list[OcrLine], stake: float | None, stake_y: float | None
) -> tuple[list[tuple[float, float]], float | None]:
    """Числовые строки-коэффициенты: ``(строки ног, общий коэффициент)``.

    За общий принимается число на высоте строки ставки, остальные — коэффициенты ног.
    """
    rows: list[tuple[float, float]] = []
    total: float | None = None
    for box in boxes:
        text = box.text.strip()
        if _DATE_RE.search(text):
            continue
        token = _PLAIN_NUMBER_RE.fullmatch(text)
        if not token:
            continue
        value = _to_float(token.group(1))
        if value is None or not (COEFFICIENT_MIN <= value <= COEFFICIENT_MAX):
            continue
        if stake is not None and abs(value - stake) < 1e-9:
            continue
        if stake_y is not None and box.y >= stake_y - 1.0:
            total = value if total is None else max(total, value)
            continue
        rows.append((box.y, value))
    return rows, total


def parse_express_lines(boxes: list[OcrLine]) -> dict[str, Any] | None:
    """Разобрать экспресс по строкам с координатами. ``None`` — это не экспресс.

    Ноги собираются по тексту (событие + прогноз), а коэффициент каждой ноги
    ищется по высоте: на скриншоте он стоит на одной строке со своим прогнозом,
    тогда как порядок строк в тексте OCR не гарантирован.
    """
    texts = [box.text for box in boxes]
    header = _express_header_index(texts)
    if header < 0:
        return None

    stake, stake_lines = _find_stake(texts)

    start, end = _legs_block_range(texts, header + 1)
    pairs = _collect_leg_pairs(texts, start, end)
    if len(pairs) < 2:
        return None

    legs = [
        {
            "event_name": texts[ei] or None,
            "prediction": texts[pi] or None,
            "coefficient": None,
        }
        for ei, pi in pairs
    ]

    stake_y = boxes[max(stake_lines)].y if stake_lines else None
    rows, total = _coefficient_rows(boxes, stake, stake_y)
    predictions = [boxes[pi].y for _, pi in pairs]
    coefficients = _bind_coefficients(rows, predictions)

    if total is not None:
        missing = [index for index, value in enumerate(coefficients) if value is None]
        if len(missing) == 1 and any(value is not None for value in coefficients):
            product = 1.0
            for value in coefficients:
                if value is not None:
                    product *= value
            if product > 0:
                coefficients[missing[0]] = round(total / product, 2)

    for leg, coefficient in zip(legs, coefficients):
        leg["coefficient"] = coefficient

    return {
        "kind": "express",
        "event_name": None,
        "prediction": None,
        "coefficient": None,
        "stake": stake,
        "legs": legs,
    }


def _recognize_boxes(data: bytes) -> list[OcrLine] | None:
    """Строки с координатами; ``None`` — координаты получить не удалось."""
    try:
        return recognize_lines(data) or None
    except OcrError:
        return None


def parse_image_full(data: bytes) -> tuple[dict[str, Any], list[OcrLine] | None]:
    """Распознать изображение и вернуть (поля ставки, строки с координатами).

    Координаты нужны, чтобы замазать сумму ставки на скриншоте перед отправкой
    в Telegram (тестовая фича). ``boxes`` — ``None``, если координаты получить
    не удалось.
    """
    boxes = _recognize_boxes(data)
    text = _lines_to_text(boxes) if boxes is not None else recognize_image(data)
    result = parse_bet_text(text)
    result.setdefault("kind", "single")
    result.setdefault("legs", [])
    express = (
        parse_express_lines(boxes) if boxes is not None else parse_express_text(text)
    )
    if express is not None:
        result.update(express)
    if result["stake"] is not None and not _stake_has_decimal(text):
        binary_text = recognize_image(data, binarize=True)
        if _stake_has_decimal(binary_text):
            binary_stake = parse_bet_text(binary_text)["stake"]
            if binary_stake is not None:
                result["stake"] = binary_stake
    result["raw_text"] = text
    return result, boxes


def parse_image(data: bytes) -> dict[str, Any]:
    """Распознать изображение и вернуть поля ставки вместе с исходным текстом.

    Если обычный проход потерял десятичную точку в сумме («200.00» -> «20000»),
    изображение распознаётся повторно с бинаризацией — она точку сохраняет.
    Из повторного прохода берётся только сумма: остальной текст он читает хуже.
    """
    result, _ = parse_image_full(data)
    return result


# --- замазывание суммы на скриншоте (тестовая фича) -------------------------

# Радиус размытия для скрытия суммы ставки.
_BLUR_RADIUS = 18
# Отступ от границ строки при вырезании региона для размытия.
_BLUR_PADDING = 12

# Расширенный паттерн «любая информация о деньгах» для замазывания.
# Ловит: ставку, сумму, выплату, баланс, прибыль, доход, потерю, выигрыш,
# возврат, банкролл, депозит/вывод, а также символы и коды валют.
# Используется ТОЛЬКО для замазывания на скриншоте (не для парсинга).
_MONEY_RE = re.compile(
    r"ставк|сумм|выплат|баланс|прибыл|доход|потер|выигрыш|проигрыш|"
    r"возврат|банкрол|депозит|вывод|пополнен|кэшбэк|бонус|"
    r"[₽$€£¥]|\brub\b|\busd\b|\beur\b|\bkzt\b|руб",
    re.I,
)


def blur_stake_region(
    image_bytes: bytes,
    boxes: list[OcrLine] | None,
    *,
    stake_value: float | None = None,
) -> bytes:
    """Замазать **любую** информацию о деньгах на скриншоте и вернуть PNG-байты.

    Размываются все строки, где встречаются деньги (ставка, сумма, выплата,
    баланс, прибыль, валюта и т. п.) — каждая во всю ширину изображения.
    Если передана ``stake_value``, дополнительно размываются строки,
    содержащие эту сумму (на случай, если метка и сумма стоят раздельно и
    сумма не попала под денежный паттерн). Если координаты недоступны или
    ничего не нашлось, замазывается нижняя половина изображения.
    """
    from PIL import Image, ImageFilter

    image = Image.open(io.BytesIO(image_bytes))
    if image.mode != "RGB":
        image = image.convert("RGB")

    blur_boxes = _money_blur_boxes(
        boxes, image.width, image.height, stake_value=stake_value
    )
    for (x0, y0, x1, y1) in blur_boxes:
        # PIL требует x0 < x1 и y0 < y1; координаты нормализуем в
        # _money_blur_boxes, но на всякий случай пропускаем вырожденные.
        if x1 <= x0 or y1 <= y0:
            continue
        region = image.crop((x0, y0, x1, y1))
        region = region.filter(ImageFilter.GaussianBlur(radius=_BLUR_RADIUS))
        image.paste(region, (x0, y0))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _stake_tokens(stake_value: float | None) -> list[str]:
    """Вернуть текстовые представления суммы для поиска в строках OCR.

    Например, 138.0 → ``['138.00', '138,00', '138']``.
    """
    if stake_value is None:
        return []
    s = f"{stake_value:.2f}"
    return [s, s.replace(".", ","), str(int(stake_value))]


def _money_blur_boxes(
    boxes: list[OcrLine] | None,
    image_width: int,
    image_height: int,
    *,
    stake_value: float | None = None,
) -> list[tuple[int, int, int, int]]:
    """Вернуть прямоугольники для размытия всех строк с деньгами.

    Для каждой строки, где встречается информация о деньгах (по ``_MONEY_RE``)
    либо содержится сумма ставки (``stake_value``), размывается **вся
    горизонтальная полоса** от левого до правого края изображения.
    Дополнительно размывается следующая по вертикали строка, если в ней есть
    цифры и она расположена близко — так ловится случай, когда метка
    («Ставка») и сумма («100.00») стоят на разных строках.
    Координаты нормализуются (Windows OCR иногда возвращает отрицательную
    ширину/высоту bounding rect).
    """
    pad = _BLUR_PADDING
    stake_tokens = _stake_tokens(stake_value)

    if not boxes:
        # Фолбэк: замазываем нижнюю половину изображения, где обычно стоит
        # сумма, ставка и возможная выплата.
        return [(0, int(image_height * 0.5), image_width, image_height)]

    # Сортируем строки по вертикали, чтобы надёжно определять «следующую».
    ordered = sorted(boxes, key=lambda b: min(float(b.y), float(b.bottom)))

    def is_money(idx: int) -> bool:
        text = ordered[idx].text
        if _MONEY_RE.search(text):
            return True
        return any(tok and tok in text for tok in stake_tokens)

    money_indices = {i for i in range(len(ordered)) if is_money(i)}
    blur_indices: set[int] = set(money_indices)

    # Для каждой денежной строки пробуем захватить следующую строку с суммой.
    for idx in money_indices:
        nxt = idx + 1
        if nxt >= len(ordered):
            continue
        nxt_box = ordered[nxt]
        nxt_top = min(float(nxt_box.y), float(nxt_box.bottom))
        cur_bottom = max(float(ordered[idx].y), float(ordered[idx].bottom))
        gap = nxt_top - cur_bottom
        # следующая строка близко (меньше ~2 высот строки) и содержит цифры
        if gap < 40 and any(ch.isdigit() for ch in nxt_box.text):
            blur_indices.add(nxt)

    result: list[tuple[int, int, int, int]] = []
    for idx in blur_indices:
        box = ordered[idx]
        top = min(float(box.y), float(box.bottom))
        bottom = max(float(box.y), float(box.bottom))
        y0 = max(0, int(top) - pad)
        y1 = min(image_height, int(bottom) + pad)
        if y1 > y0:
            result.append((0, y0, image_width, y1))

    if result:
        return result
    return [(0, int(image_height * 0.5), image_width, image_height)]
