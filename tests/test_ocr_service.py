"""Тесты распознавания ставки со скриншота: разбор текста и OCR-сервис."""

from __future__ import annotations

import pytest

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
