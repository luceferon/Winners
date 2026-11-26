"""Тесты распознавания ставки со скриншота: разбор текста и OCR-сервис."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services import ocr_service

# Текст, который Windows OCR выдаёт для скриншота 1.png (апскейл ×3).
SCREENSHOT_TEXT = "\n".join(
    [
        "Ординар #5084",
        "Прогресс - МХК Белгород",
        "(0:0) 28' 5х4",
        "2-й период: Больше (1.5)",
        "Ставка 100.00",
        "руб.",
        "1,75",
        "25/11 22:18",
        "1,75",
        "Ожидание",
    ]
)

# Текст, который Windows OCR выдаёт для скриншота 2.png (экспресс, апскейл ×3).
# Каждая нога занимает две строки — событие и прогноз; коэффициенты идут
# числовым хвостом после суммы, у четвёртой ноги коэффициент не распознан.
EXPRESS_TEXT = "\n".join(
    [
        "Экспресс #5079",
        "Лилль - Бавария",
        "Победа 2",
        "ПСЖ - Рома",
        "П1 и Тотал Больше (2.5) : да",
        "Шахтер дн - Фенербахче",
        "Обе забьют - да",
        "Брюгге - Ливерпуль",
        "Больше (2.5)",
        "Ставка 16500",
        "руб.",
        "5,86",
        "25/11 20:33 л",
        "1,62",
        "1,72",
        "1,58",
        "Ожидание",
        "Продать за 48.35 Р",
    ]
)


def test_parse_real_screenshot_text():
    result = ocr_service.parse_bet_text(SCREENSHOT_TEXT)
    assert result["event_name"] == "Прогресс - МХК Белгород"
    assert result["prediction"] == "2-й период: Больше (1.5)"
    assert result["coefficient"] == 1.75
    assert result["stake"] == 100.0


def test_parse_coefficient_with_marker():
    result = ocr_service.parse_bet_text("Зенит - Спартак\nкф 2,15\nСумма 500 руб")
    assert result["coefficient"] == 2.15
    assert result["event_name"] == "Зенит - Спартак"
    assert result["stake"] == 500.0


def test_parse_takes_first_coefficient():
    result = ocr_service.parse_bet_text("Зенит - Спартак\n1,75\n1,95")
    assert result["coefficient"] == 1.75


def test_parse_dot_decimal_coefficient():
    result = ocr_service.parse_bet_text("Прогресс - МХК Белгород\nКоэффициент 2.4\nСтавка 300")
    assert result["coefficient"] == 2.4


def test_parse_stake_on_next_line():
    text = "\n".join(
        [
            "Прогресс - МХК Белгород",
            "2-й период: Больше (1.5)",
            "Ставка",
            "100.00",
            "1,75",
        ]
    )
    result = ocr_service.parse_bet_text(text)
    assert result["stake"] == 100.0
    assert result["coefficient"] == 1.75
    assert result["event_name"] == "Прогресс - МХК Белгород"
    assert result["prediction"] == "2-й период: Больше (1.5)"


def test_parse_ignores_date_as_coefficient():
    result = ocr_service.parse_bet_text("Зенит - Спартак\n25.11.2025 22:18\n1,75")
    assert result["coefficient"] == 1.75


def test_parse_ignores_time_as_coefficient():
    result = ocr_service.parse_bet_text("Зенит - Спартак\n22:18\n1.75")
    assert result["coefficient"] == 1.75


def test_parse_stake_with_space_thousands():
    result = ocr_service.parse_bet_text("Зенит - Спартак\nСтавка 1 000.50 руб.")
    assert result["stake"] == 1000.5


def test_parse_stake_not_glued_by_misread_dot():
    # Windows OCR иногда читает десятичную точку как пробел: «200.00» -> «200 00».
    result = ocr_service.parse_bet_text("Зенит - Спартак\nСтавка 200 00 руб.")
    assert result["stake"] == 200.0


def test_parse_missing_fields_returns_none():
    result = ocr_service.parse_bet_text("Ожидание\nОрдинар #5084")
    assert result["event_name"] is None
    assert result["prediction"] is None
    assert result["coefficient"] is None
    assert result["stake"] is None


def test_parse_empty_text():
    result = ocr_service.parse_bet_text("")
    assert result == {
        "event_name": None,
        "prediction": None,
        "coefficient": None,
        "stake": None,
    }


def test_parse_express_text_collects_legs():
    result = ocr_service.parse_express_text(EXPRESS_TEXT)
    assert result is not None
    assert result["kind"] == "express"
    assert result["stake"] == 16500.0
    assert [leg["event_name"] for leg in result["legs"]] == [
        "Лилль - Бавария",
        "ПСЖ - Рома",
        "Шахтер дн - Фенербахче",
        "Брюгге - Ливерпуль",
    ]
    assert [leg["prediction"] for leg in result["legs"]] == [
        "Победа 2",
        "П1 и Тотал Больше (2.5) : да",
        "Обе забьют - да",
        "Больше (2.5)",
    ]


def test_parse_express_text_computes_missing_coefficient():
    result = ocr_service.parse_express_text(EXPRESS_TEXT)
    coefficients = [leg["coefficient"] for leg in result["legs"]]
    assert coefficients[:3] == [1.62, 1.72, 1.58]
    # Общий коэффициент 5,86 поделён на произведение распознанных.
    assert coefficients[3] == pytest.approx(5.86 / (1.62 * 1.72 * 1.58), rel=1e-2)


def test_parse_express_text_returns_none_for_single_bet():
    assert ocr_service.parse_express_text(SCREENSHOT_TEXT) is None


# Экспресс, где у каждой ноги три строки: событие, счёт, прогноз.
# Счёт не должен попадать в поле прогноза (баг, найденный при тестировании).
EXPRESS_WITH_SCORE_TEXT = "\n".join(
    [
        "Экспресс #5094",
        "Амур - Ак Барс",
        "1:4 (0:2, 1:2) П",
        "Больше (6.5)",
        "Кучинг - Пном Пень Гэлакси",
        "1:0 33'",
        "1-й тайм: Больше (0.5)",
        "Ставка 100.00",
        "руб.",
        "3,17",
        "1,73",
        "1,83",
        "Ожидание",
    ]
)


def test_parse_express_text_skips_score_lines():
    result = ocr_service.parse_express_text(EXPRESS_WITH_SCORE_TEXT)
    assert result is not None
    assert result["stake"] == 100.0
    assert [leg["event_name"] for leg in result["legs"]] == [
        "Амур - Ак Барс",
        "Кучинг - Пном Пень Гэлакси",
    ]
    assert [leg["prediction"] for leg in result["legs"]] == [
        "Больше (6.5)",
        "1-й тайм: Больше (0.5)",
    ]


def test_parse_express_lines_skips_score_lines_and_binds_coefficients():
    boxes = [
        ocr_service.OcrLine("Экспресс #5094", 22.0, 3.0, 313.0, 40.0),
        ocr_service.OcrLine("Амур - Ак Барс", 90.0, 110.0, 393.0, 147.0),
        ocr_service.OcrLine("1:4 (0:2, 1:2) П", 92.0, 156.0, 400.0, 193.0),
        ocr_service.OcrLine("Больше (6.5)", 92.0, 200.0, 258.0, 237.0),
        ocr_service.OcrLine("Кучинг - Пном Пень Гэлакси", 90.0, 290.0, 560.0, 327.0),
        ocr_service.OcrLine("1:0 33'", 92.0, 336.0, 250.0, 373.0),
        ocr_service.OcrLine("1-й тайм: Больше (0.5)", 92.0, 380.0, 400.0, 417.0),
        ocr_service.OcrLine("Ставка 100.00", 13.0, 470.0, 252.0, 507.0),
        ocr_service.OcrLine("руб.", 263.0, 471.0, 327.0, 508.0),
        ocr_service.OcrLine("3,17", 540.0, 470.0, 610.0, 507.0),
        ocr_service.OcrLine("1,73", 730.0, 200.0, 800.0, 237.0),
        ocr_service.OcrLine("1,83", 730.0, 380.0, 800.0, 417.0),
        ocr_service.OcrLine("Ожидание", 880.0, 470.0, 1055.0, 507.0),
    ]
    result = ocr_service.parse_express_lines(boxes)
    assert result is not None
    assert [leg["event_name"] for leg in result["legs"]] == [
        "Амур - Ак Барс",
        "Кучинг - Пном Пень Гэлакси",
    ]
    assert [leg["prediction"] for leg in result["legs"]] == [
        "Больше (6.5)",
        "1-й тайм: Больше (0.5)",
    ]
    coefficients = [leg["coefficient"] for leg in result["legs"]]
    assert coefficients == [1.73, 1.83]


# Строки экспресса с координатами (апскейл ×3, как на 2.png). Порядок строк-
# коэффициентов в тексте намеренно перемешан: привязывать их нужно по высоте.
EXPRESS_BOXES = [
    ocr_service.OcrLine("Экспресс #5079", 22.0, 3.0, 313.0, 40.0),
    ocr_service.OcrLine("Лилль - Бавария", 90.0, 110.0, 393.0, 147.0),
    ocr_service.OcrLine("Победа 2", 92.0, 156.0, 258.0, 193.0),
    ocr_service.OcrLine("ПСЖ - Рома", 91.0, 269.0, 313.0, 306.0),
    ocr_service.OcrLine("П1 и Тотал Больше (2.5) : да", 92.0, 315.0, 607.0, 352.0),
    ocr_service.OcrLine("Шахтер дн - Фенербахче", 91.0, 425.0, 550.0, 462.0),
    ocr_service.OcrLine("Обе забьют - да", 91.0, 474.0, 384.0, 511.0),
    ocr_service.OcrLine("Брюгге - Ливерпуль", 91.0, 587.0, 455.0, 624.0),
    ocr_service.OcrLine("Больше (2.5)", 92.0, 633.0, 320.0, 670.0),
    ocr_service.OcrLine("Ставка 16500", 13.0, 728.0, 252.0, 765.0),
    ocr_service.OcrLine("руб.", 263.0, 729.0, 327.0, 766.0),
    ocr_service.OcrLine("5,86", 649.0, 728.0, 719.0, 765.0),
    ocr_service.OcrLine("25/11 20:33 л", 838.0, 3.0, 1101.0, 40.0),
    ocr_service.OcrLine("1,58", 1032.0, 476.0, 1106.0, 513.0),
    ocr_service.OcrLine("1,62", 1032.0, 158.0, 1107.0, 195.0),
    ocr_service.OcrLine("1,72", 1032.0, 317.0, 1107.0, 354.0),
    ocr_service.OcrLine("Ожидание", 880.0, 728.0, 1055.0, 765.0),
    ocr_service.OcrLine("Продать за 48.35 Р", 370.0, 861.0, 751.0, 898.0),
]


def test_parse_express_lines_binds_coefficients_by_position():
    result = ocr_service.parse_express_lines(EXPRESS_BOXES)
    assert result is not None
    assert result["kind"] == "express"
    assert result["stake"] == 16500.0
    assert [leg["event_name"] for leg in result["legs"]] == [
        "Лилль - Бавария",
        "ПСЖ - Рома",
        "Шахтер дн - Фенербахче",
        "Брюгге - Ливерпуль",
    ]
    coefficients = [leg["coefficient"] for leg in result["legs"]]
    # 1,58 стоит в тексте раньше 1,72, но по высоте принадлежит третьей ноге.
    assert coefficients[:3] == [1.62, 1.72, 1.58]
    assert coefficients[3] == pytest.approx(5.86 / (1.62 * 1.72 * 1.58), rel=1e-2)


def test_parse_express_lines_keeps_all_present_coefficients():
    boxes = list(EXPRESS_BOXES)
    boxes.append(ocr_service.OcrLine("1,33", 1032.0, 635.0, 1107.0, 672.0))
    result = ocr_service.parse_express_lines(boxes)
    assert [leg["coefficient"] for leg in result["legs"]] == [1.62, 1.72, 1.58, 1.33]


def test_parse_image_uses_line_positions_for_express(monkeypatch):
    monkeypatch.setattr(
        ocr_service, "recognize_lines", lambda data, binarize=False: EXPRESS_BOXES
    )
    monkeypatch.setattr(
        ocr_service, "recognize_image", lambda data, binarize=False: EXPRESS_TEXT
    )
    result = ocr_service.parse_image(b"fake")
    assert result["kind"] == "express"
    assert [leg["coefficient"] for leg in result["legs"]][:3] == [1.62, 1.72, 1.58]


def test_parse_image_detects_express(monkeypatch):
    def fake_recognize(data, binarize=False):
        if binarize:
            return "Экспресс #5079\nСтавка 165.00 руб\n5,86"
        return EXPRESS_TEXT

    monkeypatch.setattr(ocr_service, "recognize_image", fake_recognize)
    result = ocr_service.parse_image(b"fake")
    assert result["kind"] == "express"
    assert result["event_name"] is None
    assert result["coefficient"] is None
    assert result["stake"] == 165.0
    assert len(result["legs"]) == 4
    assert result["legs"][0]["coefficient"] == 1.62


def test_parse_image_single_bet_kind(monkeypatch):
    monkeypatch.setattr(ocr_service, "recognize_image", lambda data, binarize=False: SCREENSHOT_TEXT)
    result = ocr_service.parse_image(b"fake")
    assert result["kind"] == "single"
    assert result["legs"] == []


def test_read_clipboard_image_returns_none_when_empty(monkeypatch):
    from PIL import ImageGrab

    monkeypatch.setattr(ImageGrab, "grabclipboard", lambda: None)
    assert ocr_service.read_clipboard_image() is None


def test_read_clipboard_image_encodes_bitmap(monkeypatch):
    from PIL import Image, ImageGrab

    monkeypatch.setattr(ImageGrab, "grabclipboard", lambda: Image.new("RGB", (10, 10), "white"))
    data = ocr_service.read_clipboard_image()
    assert data is not None
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_read_clipboard_image_reads_file_reference(monkeypatch, tmp_path):
    from PIL import Image, ImageGrab

    target = tmp_path / "shot.png"
    Image.new("RGB", (20, 20), "white").save(target)
    monkeypatch.setattr(ImageGrab, "grabclipboard", lambda: [str(target)])
    data = ocr_service.read_clipboard_image()
    assert data == target.read_bytes()


def test_read_clipboard_image_raises_on_unreadable_file(monkeypatch, tmp_path):
    from pathlib import Path
    from PIL import Image, ImageGrab

    target = tmp_path / "shot.png"
    Image.new("RGB", (20, 20), "white").save(target)
    monkeypatch.setattr(ImageGrab, "grabclipboard", lambda: [str(target)])

    def boom(self):
        raise OSError("locked")

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(ocr_service.OcrError):
        ocr_service.read_clipboard_image()


def test_parse_image_collects_raw_text(monkeypatch):
    monkeypatch.setattr(ocr_service, "recognize_image", lambda data: SCREENSHOT_TEXT)
    result = ocr_service.parse_image(b"fake-image")
    assert result["coefficient"] == 1.75
    assert result["raw_text"] == SCREENSHOT_TEXT


def test_parse_image_recovers_dot_lost_by_ocr(monkeypatch):
    def fake_recognize(data, binarize=False):
        if binarize:
            return "Торпедо НН - Сибирь\n2-й период: Больше (1.5)\nСтавка 200.00 руб.\n1,82"
        return "Торпедо НН - Сибирь\n2-й период: Больше (1.5)\nСтавка 20000\n1,82"

    monkeypatch.setattr(ocr_service, "recognize_image", fake_recognize)
    result = ocr_service.parse_image(b"fake")
    assert result["stake"] == 200.0


def test_parse_image_keeps_stake_when_dot_present(monkeypatch):
    calls: list[bool] = []

    def fake_recognize(data, binarize=False):
        calls.append(binarize)
        return "Зенит - Спартак\nСтавка 100.00\n1,75"

    monkeypatch.setattr(ocr_service, "recognize_image", fake_recognize)
    result = ocr_service.parse_image(b"fake")
    assert result["stake"] == 100.0
    assert calls == [False]


def test_prepare_image_binarize_makes_two_tone():
    import io

    from PIL import Image

    img = Image.new("L", (10, 10), 255)
    img.putpixel((5, 5), 0)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    out = ocr_service._prepare_image(buffer.getvalue(), binarize=True)
    assert set(out.convert("L").getdata()) <= {0, 255}


def test_recognize_image_rejects_empty_bytes():
    with pytest.raises(ocr_service.OcrError):
        ocr_service.recognize_image(b"")


def test_recognize_image_rejects_garbage_bytes():
    with pytest.raises(ocr_service.OcrError):
        ocr_service.recognize_image(b"not-an-image")


# --- замазывание суммы на скриншоте (тестовая фича) -------------------------


def _make_image_bytes(width: int = 400, height: int = 200) -> bytes:
    """Создать тестовое изображение с разными пикселями в зоне суммы."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    pixels = img.load()
    # В нижней половине (где обычно сумма) делаем контрастный паттерн
    for y in range(height // 2, height):
        for x in range(width):
            pixels[x, y] = ((x * 7 + y * 13) % 256, (x * 3) % 256, (y * 5) % 256)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def test_blur_stake_region_returns_bytes():
    boxes = [ocr_service.OcrLine("Ставка 100 руб.", 10, 150, 200, 180)]
    out = ocr_service.blur_stake_region(_make_image_bytes(), boxes)
    assert isinstance(out, bytes)
    assert out[:8] == b"\x89PNG\r\n\x1a\n"  # PNG-сигнатура


def test_blur_stake_region_changes_stake_pixels():
    """Размытие применяется ко всей ширине строки со ставкой."""
    original = _make_image_bytes()
    boxes = [ocr_service.OcrLine("Ставка 100 руб.", 10, 150, 200, 180)]
    out = ocr_service.blur_stake_region(original, boxes)
    img_orig = Image.open(io.BytesIO(original))
    img_out = Image.open(io.BytesIO(out))
    width, height = img_orig.size
    px_orig = img_orig.load()
    px_out = img_out.load()
    # полоса размытия: вся ширина, y от 150-pad до 180+pad
    pad = ocr_service._BLUR_PADDING
    y0, y1 = max(0, 150 - pad), min(height, 180 + pad)
    changed = 0
    for x in range(width):
        for y in range(y0, y1):
            if px_orig[x, y] != px_out[x, y]:
                changed += 1
    # реально заменили много пикселей по всей ширине
    assert changed > 100


def test_blur_stake_region_fallback_without_boxes():
    """Если координат нет — замазывается нижняя половина изображения."""
    original = _make_image_bytes()
    out = ocr_service.blur_stake_region(original, None)
    img_orig = Image.open(io.BytesIO(original))
    img_out = Image.open(io.BytesIO(out))
    px_orig = img_orig.load()
    px_out = img_out.load()
    width, height = img_orig.size
    fallback_top = int(height * 0.5)
    changed = sum(
        1
        for x in range(width)
        for y in range(fallback_top, height)
        if px_orig[x, y] != px_out[x, y]
    )
    assert changed > 100


def test_blur_stake_region_handles_degenerate_boxes():
    """Windows OCR может вернуть отрицательную ширину/высоту бокса.

    Такие боксы не должны приводить к падению PIL crop.
    """
    original = _make_image_bytes()
    # box с right < x и bottom < y (отрицательная ширина/высота)
    boxes = [ocr_service.OcrLine("Ставка 100 руб.", 100, 150, 50, 80)]
    # не должно упасть
    out = ocr_service.blur_stake_region(original, boxes)
    assert isinstance(out, bytes)
    assert out[:8] == b"\x89PNG\r\n\x1a\n"


def test_blur_stake_region_handles_zero_boxes():
    """Бокс с нулевой площадью не должен приводить к падению."""
    original = _make_image_bytes()
    boxes = [ocr_service.OcrLine("Ставка 100 руб.", 50, 50, 50, 50)]
    out = ocr_service.blur_stake_region(original, boxes)
    assert isinstance(out, bytes)
    assert out[:8] == b"\x89PNG\r\n\x1a\n"


def test_blur_stake_region_blurs_amount_on_next_line():
    """Если «Ставка» и сумма на разных строках — размываются обе."""
    original = _make_image_bytes()
    boxes = [
        ocr_service.OcrLine("Ставка", 10, 150, 80, 175),
        ocr_service.OcrLine("100.00", 10, 180, 80, 205),
    ]
    out = ocr_service.blur_stake_region(original, boxes)
    img_orig = Image.open(io.BytesIO(original))
    img_out = Image.open(io.BytesIO(out))
    width, height = img_orig.size
    px_orig = img_orig.load()
    px_out = img_out.load()
    pad = ocr_service._BLUR_PADDING
    # размыта и строка «Ставка», и строка «100.00»
    for y0, y1 in [(150 - pad, 175 + pad), (180 - pad, 205 + pad)]:
        changed = sum(
            1
            for x in range(width)
            for y in range(max(0, y0), min(height, y1))
            if px_orig[x, y] != px_out[x, y]
        )
        assert changed > 50


def test_blur_stake_region_blurs_all_money_lines():
    """Размываются все строки с деньгами (ставка + возможная выплата)."""
    original = _make_image_bytes()
    boxes = [
        ocr_service.OcrLine("Ставка 100 руб.", 10, 100, 200, 125),
        ocr_service.OcrLine("Возможная выплата 185 руб.", 10, 200, 260, 225),
    ]
    out = ocr_service.blur_stake_region(original, boxes)
    img_orig = Image.open(io.BytesIO(original))
    img_out = Image.open(io.BytesIO(out))
    width, height = img_orig.size
    px_orig = img_orig.load()
    px_out = img_out.load()
    pad = ocr_service._BLUR_PADDING
    for y0, y1 in [(100 - pad, 125 + pad), (200 - pad, 225 + pad)]:
        changed = sum(
            1
            for x in range(width)
            for y in range(max(0, y0), min(height, y1))
            if px_orig[x, y] != px_out[x, y]
        )
        assert changed > 50


def test_parse_image_full_returns_boxes():
    """parse_image_full возвращает кортеж (результат, boxes)."""
    data = _make_image_bytes()
    parsed, result_boxes = ocr_service.parse_image_full(data)
    assert isinstance(parsed, dict)
    # при пустых байтах _recognize_boxes вернёт None
    assert result_boxes is None or isinstance(result_boxes, list)

