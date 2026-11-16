"""Формирование CSV-файлов для экспорта истории ставок и статистики.

CSV отдаётся с BOM и разделителем «;», чтобы Excel (в том числе с русской
локалью) корректно открывал кириллицу и не сваливал строку в одну ячейку.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Iterable, Sequence
from urllib.parse import quote

from fastapi import Response

from app.defaults import STATUS_LABELS
from app.models import Bet
from app.services import timeutil

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
CSV_DELIMITER = ";"
EXPORT_LIMIT = 10_000
_BOM = "\ufeff"

KIND_LABELS = {"single": "Одиночная", "express": "Экспресс"}

BETS_HEADER = [
    "Дата",
    "Тип",
    "Вид спорта",
    "Событие",
    "Прогноз",
    "Коэффициент",
    "Сумма",
    "Источник",
    "Статус",
    "Выплата",
    "Прибыль",
    "Комментарий",
]


def _format_datetime(value: datetime | None) -> str:
    local = timeutil.to_local(value)
    return local.strftime("%d.%m.%Y %H:%M") if local else ""


def _format_number(value: float | None, digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{float(value):.{digits}f}"


def build_csv(rows: Iterable[Sequence[Any]], header: Sequence[str] | None = None) -> str:
    """Собрать CSV-текст: разделитель «;», BOM для корректной кириллицы в Excel."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=CSV_DELIMITER, lineterminator="\r\n")
    if header:
        writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return _BOM + buffer.getvalue()


def csv_response(
    filename: str,
    rows: Iterable[Sequence[Any]],
    *,
    header: Sequence[str] | None = None,
) -> Response:
    """HTTP-ответ с CSV-файлом (Content-Disposition: attachment)."""
    disposition = f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=build_csv(rows, header),
        media_type=CSV_MEDIA_TYPE,
        headers={"Content-Disposition": disposition},
    )


def bets_rows(bets: Iterable[Bet]) -> list[list[str]]:
    """Строки экспорта истории ставок."""
    rows: list[list[str]] = []
    for bet in bets:
        rows.append(
            [
                _format_datetime(bet.created_at),
                KIND_LABELS.get(bet.kind, bet.kind),
                bet.sport,
                bet.event_name,
                bet.prediction or "",
                _format_number(bet.coefficient),
                _format_number(bet.stake),
                bet.source_name or "",
                STATUS_LABELS.get(bet.status, bet.status),
                _format_number(bet.payout),
                _format_number(bet.profit),
                (bet.comment or "").replace("\n", " ").strip(),
            ]
        )
    return rows


def stats_rows(summary: dict[str, Any]) -> list[list[str]]:
    """Строки экспорта статистики: сводка и разбивки по видам спорта и источникам."""
    counts = summary.get("counts", {})
    amounts = summary.get("amounts", {})
    metrics = summary.get("metrics", {})
    period = summary.get("range", {})

    rows: list[list[str]] = [["Показатель", "Значение"]]
    rows.append(["Период", f"{period.get('from') or '—'} — {period.get('to') or '—'}"])
    rows.append(["Всего ставок", str(counts.get("total", 0))])
    rows.append(["Завершено", str(counts.get("settled", 0))])
    rows.append(["Выигрышных", str(counts.get("won", 0))])
    rows.append(["Проигрышных", str(counts.get("lost", 0))])
    rows.append(["Возврат", str(counts.get("push", 0))])
    rows.append(["Активных", str(counts.get("pending", 0))])
    rows.append(["Оборот", _format_number(amounts.get("staked_total"))])
    rows.append(["Сумма выигрышных", _format_number(amounts.get("won_stake"))])
    rows.append(["Сумма проигрышных", _format_number(amounts.get("lost_stake"))])
    rows.append(["В игре", _format_number(amounts.get("active"))])
    rows.append(["Финансовый результат", _format_number(metrics.get("profit"))])
    rows.append(["ROI, %", _format_number(metrics.get("roi_percent"))])
    rows.append(["Проходимость, %", _format_number(metrics.get("win_rate_percent"))])
    rows.append(["Средний коэффициент", _format_number(metrics.get("avg_coefficient"))])
    rows.append(["Прибыль на ставку", _format_number(metrics.get("profit_per_bet"))])

    rows.append([])
    rows.append(["Разбивка по видам спорта"])
    rows.append(
        ["Вид спорта", "Ставок", "Выиграно", "Проиграно", "Проходимость, %", "Оборот", "Результат", "Ср. коэффициент"]
    )
    for item in summary.get("by_sport", []):
        rows.append(_group_row(item))

    rows.append([])
    rows.append(["Разбивка по источникам"])
    rows.append(
        ["Источник", "Ставок", "Выиграно", "Проиграно", "Проходимость, %", "Оборот", "Результат", "Ср. коэффициент"]
    )
    for item in summary.get("by_source", []):
        rows.append(_group_row(item))

    return rows


def _group_row(item: dict[str, Any]) -> list[str]:
    return [
        str(item.get("name", "")),
        str(item.get("bets", 0)),
        str(item.get("won", 0)),
        str(item.get("lost", 0)),
        _format_number(item.get("win_rate_percent")),
        _format_number(item.get("stake")),
        _format_number(item.get("profit")),
        _format_number(item.get("avg_coefficient")),
    ]
