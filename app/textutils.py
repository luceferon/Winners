"""Нормализация и нечёткое сопоставление названий событий.

Используется модулем парсинга для поиска нужного матча по названию,
введённому пользователем. Комбинирует сравнение строк, совпадение слов
и фонетические коды (Soundex + транслитерация кириллицы).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_PUNCT_RE = re.compile(r"[^0-9a-zа-я\s]+")

# Грубая транслитерация кириллицы для фонетического сравнения.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "iu", "я": "ia",
}

_SOUNDEX_CODES = {
    "B": "1", "F": "1", "P": "1", "V": "1",
    "C": "2", "G": "2", "J": "2", "K": "2", "Q": "2", "S": "2", "X": "2", "Z": "2",
    "D": "3", "T": "3",
    "L": "4",
    "M": "5", "N": "5",
    "R": "6",
}

# Слова, не влияющие на идентификацию матча.
STOPWORDS = {
    "фк", "fc", "ск", "bk", "team", "команда", "матч", "match", "игра", "game",
    "vs", "против", "против", "и", "and", "the", "клуб", "club", "спорт", "sport",
}


def normalize_title(value: str | None) -> str:
    """Привести название события к сравнимому виду."""
    if not value:
        return ""
    text = value.strip().lower().replace("ё", "е")
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def transliterate(value: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in value)


def soundex(token: str) -> str:
    """Фонетический код латинского слова (упрощённый Soundex)."""
    word = "".join(ch for ch in transliterate(token).upper() if ch.isalpha())
    if not word:
        return ""
    first = word[0]
    prev_code = _SOUNDEX_CODES.get(first, "")
    result = [first]
    for ch in word[1:]:
        code = _SOUNDEX_CODES.get(ch, "")
        if code and code != prev_code:
            result.append(code)
        if ch not in {"H", "W"}:
            prev_code = code
    return ("".join(result) + "000")[:4]


def tokens(value: str) -> list[str]:
    return [tok for tok in normalize_title(value).split() if tok and tok not in STOPWORDS]


def _jaccard(left: set, right: set) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def phonetic_key(token: str) -> str:
    """Фонетический код слова, не зависящий от алфавита.

    Отличие от :func:`soundex`: первая буква тоже кодируется классом, поэтому
    кириллица и её латинский эквивалент дают один код
    («ковбойс» → «212» и «cowboys» → «212»).
    """
    latin = transliterate(token).upper()
    codes: list[str] = []
    for ch in latin:
        if not ch.isalpha():
            continue
        code = _SOUNDEX_CODES.get(ch, "")
        if code and (not codes or codes[-1] != code):
            codes.append(code)
    return "".join(codes)


def _best_token_match(token: str, others: list[str]) -> float:
    """Наилучшее совпадение слова с одним из слов другого названия (0…1)."""
    if token in others:
        return 1.0
    latin = transliterate(token)
    key = phonetic_key(token)
    best = 0.0
    for other in others:
        other_latin = transliterate(other)
        ratio = SequenceMatcher(None, latin, other_latin).ratio()
        if key and key == phonetic_key(other):
            ratio = max(ratio, 0.9)
        # Часть слова внутри другого: «49-е» ↔ «49ers», «сан» ↔ «санкт».
        if len(latin) >= 2 and (latin in other_latin or other_latin in latin):
            ratio = max(ratio, 0.85)
        best = max(best, ratio)
    return best


def _coverage(tokens_query: list[str], tokens_other: list[str]) -> float:
    """Доля слов запроса, для которых нашлось совпадение в другом названии."""
    if not tokens_query or not tokens_other:
        return 0.0
    return sum(_best_token_match(token, tokens_other) for token in tokens_query) / len(tokens_query)


def _alignment(tokens_a: list[str], tokens_b: list[str]) -> float:
    """Словесное выравнивание названий: каждое слово ищет пару в другом.

    Вес смещён в сторону покрытия запроса — пользователь может указать только
    одну команду, и это всё равно уверенное совпадение.
    """
    forward = _coverage(tokens_a, tokens_b)
    backward = _coverage(tokens_b, tokens_a)
    return 0.7 * forward + 0.3 * backward


def similarity(left: str | None, right: str | None) -> float:
    """Оценка схожести двух названий событий в диапазоне 0…1.

    Устойчива к разнице алфавитов: русское название сравнивается с английским
    через транслитерацию и фонетические коды, поэтому «Даллас Ковбойс —
    Сан-Франциско 49-е» находит «Dallas Cowboys — San Francisco 49ers».
    """
    a, b = normalize_title(left), normalize_title(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    seq = SequenceMatcher(None, transliterate(a), transliterate(b)).ratio()

    tokens_a, tokens_b = tokens(a), tokens(b)
    align = _alignment(tokens_a, tokens_b)
    word_score = _jaccard(set(tokens_a), set(tokens_b))

    keys_a = {phonetic_key(tok) for tok in tokens_a} - {""}
    keys_b = {phonetic_key(tok) for tok in tokens_b} - {""}
    phon_score = _jaccard(keys_a, keys_b)

    # Совпадение может быть частичным: пользователь указал одну команду или
    # название короче события. Если более короткое название покрыто почти
    # целиком — это по-прежнему уверенное совпадение.
    if a in b or b in a:
        bonus = 0.15
    elif max(_coverage(tokens_a, tokens_b), _coverage(tokens_b, tokens_a)) >= 0.8:
        bonus = 0.10
    else:
        bonus = 0.0

    score = 0.25 * seq + 0.40 * align + 0.20 * phon_score + 0.15 * word_score + bonus
    return round(min(max(score, 0.0), 1.0), 4)
