"""Тесты нормализации названий и нечёткого сопоставления событий."""

from __future__ import annotations

from app.textutils import normalize_title, similarity, soundex, tokens


def test_normalize_title_basic():
    assert normalize_title("  Зенит  —  Спартак ") == "зенит спартак"
    assert normalize_title("Real Madrid!") == "real madrid"
    assert normalize_title("Ёж") == "еж"
    assert normalize_title(None) == ""
    assert normalize_title("") == ""


def test_similarity_identical_is_one():
    assert similarity("Зенит — Спартак", "зенит спартак") == 1.0


def test_similarity_ordering_and_bounds():
    close = similarity("Зенит — Спартак", "Зенит Спартак")
    far = similarity("Зенит — Спартак", "Барселона — Реал")
    assert close > far
    assert 0.0 <= far <= 1.0
    assert similarity("", "Зенит") == 0.0


def test_similarity_cross_language():
    """Русское название должно находить английское (разные алфавиты)."""
    score = similarity(
        "Даллас Ковбойс - Сан-Франциско 49-е",
        "Dallas Cowboys — San Francisco 49ers",
    )
    assert score >= 0.62
    assert similarity("Даллас Ковбойс", "Барселона — Реал") < 0.5


def test_soundex_is_deterministic_and_fixed_length():
    assert soundex("Зенит") == soundex("Зенит")
    assert len(soundex("Zenit")) == 4
    assert soundex("") == ""


def test_tokens_drop_stopwords():
    result = tokens("ФК Зенит")
    assert "зенит" in result
    assert "фк" not in result
