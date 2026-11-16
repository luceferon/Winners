"""Расчёт агрегированной статистики по ставкам."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.defaults import SETTLED_STATUSES, STATUS_LABELS, STATUS_PENDING
from app.models import Bet
from app.services import timeutil

COEFFICIENT_BUCKETS: list[tuple[str, float, float]] = [
    ("до 1.5", 0.0, 1.5),
    ("1.5 – 2.0", 1.5, 2.0),
    ("2.0 – 3.0", 2.0, 3.0),
    ("3.0 – 5.0", 3.0, 5.0),
    ("5.0 +", 5.0, float("inf")),
]

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def _percent(part: float, whole: float) -> float:
    return _round(part / whole * 100, 1) if whole else 0.0


def fetch_bets(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sport: str | None = None,
    source_id: int | None = None,
) -> list[Bet]:
    stmt = select(Bet)
    if date_from is not None:
        stmt = stmt.where(Bet.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Bet.created_at <= date_to)
    if sport and sport != "all":
        stmt = stmt.where(Bet.sport == sport)
    if source_id:
        stmt = stmt.where(Bet.source_id == source_id)
    return list(db.execute(stmt.order_by(Bet.created_at.asc())).unique().scalars().all())


def _counts(bets: Iterable[Bet]) -> dict[str, int]:
    counts = {"total": 0, "won": 0, "lost": 0, "pending": 0, "push": 0, "cancelled": 0}
    for bet in bets:
        counts["total"] += 1
        if bet.status in counts:
            counts[bet.status] += 1
    counts["settled"] = counts["won"] + counts["lost"] + counts["push"] + counts["cancelled"]
    return counts


def _amounts(bets: Iterable[Bet]) -> dict[str, float]:
    amounts = {
        "staked_total": 0.0,
        "active": 0.0,
        "won_stake": 0.0,
        "lost_stake": 0.0,
        "push_stake": 0.0,
        "cancelled_stake": 0.0,
        "won_payout": 0.0,
        "settled_stake": 0.0,
        "potential_payout": 0.0,
    }
    for bet in bets:
        amounts["staked_total"] += bet.stake
        amounts["potential_payout"] += bet.stake * bet.coefficient
        if bet.status == STATUS_PENDING:
            amounts["active"] += bet.stake
        elif bet.status == "won":
            amounts["won_stake"] += bet.stake
            amounts["won_payout"] += bet.payout
            amounts["settled_stake"] += bet.stake
        elif bet.status == "lost":
            amounts["lost_stake"] += bet.stake
            amounts["settled_stake"] += bet.stake
        elif bet.status == "push":
            amounts["push_stake"] += bet.stake
            amounts["won_payout"] += bet.payout
            amounts["settled_stake"] += bet.stake
        elif bet.status == "cancelled":
            amounts["cancelled_stake"] += bet.stake
    return {key: _round(value) for key, value in amounts.items()}


def _metrics(bets: list[Bet], counts: dict[str, int], amounts: dict[str, float]) -> dict[str, Any]:
    decided = counts["won"] + counts["lost"]
    profit = _round(amounts["won_payout"] - amounts["won_stake"] - amounts["lost_stake"])
    coefficients = [bet.coefficient for bet in bets]
    won_coefficients = [bet.coefficient for bet in bets if bet.status == "won"]
    stakes = [bet.stake for bet in bets]

    return {
        "profit": profit,
        "roi_percent": _percent(profit, amounts["settled_stake"]),
        "win_rate_percent": _percent(counts["won"], decided),
        "avg_coefficient": _round(sum(coefficients) / len(coefficients)) if coefficients else 0.0,
        "avg_coefficient_won": _round(sum(won_coefficients) / len(won_coefficients))
        if won_coefficients
        else 0.0,
        "avg_stake": _round(sum(stakes) / len(stakes)) if stakes else 0.0,
        "profit_per_bet": _round(profit / decided) if decided else 0.0,
        "turnover": amounts["staked_total"],
    }


def _timeline(bets: list[Bet], date_from: datetime | None, date_to: datetime | None) -> list[dict]:
    """Динамика по дням с накопленным финансовым результатом и просадкой."""
    buckets: dict[date, dict[str, float]] = defaultdict(
        lambda: {
            "bets": 0,
            "staked": 0.0,
            "settled_stake": 0.0,
            "payout": 0.0,
            "profit": 0.0,
            "won": 0,
            "lost": 0,
        }
    )
    for bet in bets:
        day = timeutil.local_date(bet.created_at)
        if day is None:
            continue
        bucket = buckets[day]
        bucket["bets"] += 1
        bucket["staked"] += bet.stake
        if bet.status == "won":
            bucket["won"] += 1
            bucket["settled_stake"] += bet.stake
            bucket["payout"] += bet.payout
            bucket["profit"] += bet.payout - bet.stake
        elif bet.status == "lost":
            bucket["lost"] += 1
            bucket["settled_stake"] += bet.stake
            bucket["profit"] -= bet.stake
        elif bet.status == "push":
            bucket["settled_stake"] += bet.stake
            bucket["payout"] += bet.payout

    if not buckets:
        return []

    first_day = timeutil.local_date(date_from) or min(buckets)
    last_day = timeutil.local_date(date_to) or max(buckets)
    if first_day is None or last_day is None:
        first_day, last_day = min(buckets), max(buckets)
    span = (last_day - first_day).days
    if span > 400:  # слишком длинный период — только дни с данными
        filled = sorted(buckets)
    else:
        filled = [first_day + timedelta(days=offset) for offset in range(span + 1)]

    cumulative = 0.0
    cumulative_stake = 0.0
    result: list[dict] = []
    for day in filled:
        bucket = buckets.get(day)
        profit = _round(bucket["profit"]) if bucket else 0.0
        cumulative += profit
        cumulative_stake += bucket["settled_stake"] if bucket else 0.0
        result.append(
            {
                "date": day.isoformat(),
                "bets": int(bucket["bets"]) if bucket else 0,
                "staked": _round(bucket["staked"]) if bucket else 0.0,
                "payout": _round(bucket["payout"]) if bucket else 0.0,
                "profit": profit,
                "cumulative_profit": _round(cumulative),
                "cumulative_stake": _round(cumulative_stake),
                "cumulative_roi_percent": _percent(cumulative, cumulative_stake),
                "won": int(bucket["won"]) if bucket else 0,
                "lost": int(bucket["lost"]) if bucket else 0,
            }
        )
    return result


def _drawdown(timeline: list[dict]) -> dict[str, Any]:
    """Просадка от пика накопленного результата: пик, текущая и максимальная."""
    peak = 0.0
    max_drawdown = 0.0
    current = 0.0
    for row in timeline:
        cumulative = float(row["cumulative_profit"])
        peak = max(peak, cumulative)
        current = _round(cumulative - peak)
        row["peak"] = _round(peak)
        row["drawdown"] = current
        max_drawdown = min(max_drawdown, current)
    return {
        "peak_profit": _round(peak),
        "current_drawdown": _round(current),
        "max_drawdown": _round(max_drawdown),
    }


def _streaks(bets: list[Bet]) -> dict[str, Any]:
    """Серии побед и поражений по решённым ставкам в хронологическом порядке.

    Учитываются только статусы «won» и «lost» (возврат и отмена не прерывают
    серию и не участвуют в ней). `current_streak` положительна для серии побед
    и отрицательна для серии поражений.
    """
    max_win = 0
    max_lose = 0
    current = 0
    kind: str | None = None
    for bet in bets:
        if bet.status not in {"won", "lost"}:
            continue
        if bet.status == kind:
            current += 1
        else:
            kind = bet.status
            current = 1
        if bet.status == "won":
            max_win = max(max_win, current)
        else:
            max_lose = max(max_lose, current)
    return {
        "max_win_streak": max_win,
        "max_lose_streak": max_lose,
        "current_streak": (current if kind == "won" else -current) if kind else 0,
        "current_streak_kind": kind,
    }


def _monthly_rows(bets: list[Bet]) -> list[dict]:
    """Разбивка по календарным месяцам (локальное время), от ранних к поздним."""
    groups: dict[str, dict[str, float]] = {}
    for bet in bets:
        day = timeutil.local_date(bet.created_at)
        if day is None:
            continue
        key = f"{day.year:04d}-{day.month:02d}"
        group = groups.setdefault(
            key,
            {"bets": 0, "won": 0, "lost": 0, "pending": 0, "stake": 0.0, "settled_stake": 0.0, "payout": 0.0},
        )
        group["bets"] += 1
        group["stake"] += bet.stake
        if bet.status == "won":
            group["won"] += 1
            group["settled_stake"] += bet.stake
            group["payout"] += bet.payout
        elif bet.status == "lost":
            group["lost"] += 1
            group["settled_stake"] += bet.stake
        elif bet.status == "push":
            group["settled_stake"] += bet.stake
            group["payout"] += bet.payout
        elif bet.status == "pending":
            group["pending"] += 1

    rows: list[dict] = []
    for key in sorted(groups):
        group = groups[key]
        decided = group["won"] + group["lost"]
        profit = group["payout"] - group["settled_stake"]
        rows.append(
            {
                "name": key,
                "bets": int(group["bets"]),
                "won": int(group["won"]),
                "lost": int(group["lost"]),
                "pending": int(group["pending"]),
                "stake": _round(group["stake"]),
                "profit": _round(profit),
                "win_rate_percent": _percent(group["won"], decided),
                "roi_percent": _percent(profit, group["settled_stake"]),
            }
        )
    return rows


def _group_rows(bets: list[Bet], key_func) -> list[dict]:  # noqa: ANN001
    groups: dict[str, dict] = {}
    for bet in bets:
        key = key_func(bet) or "—"
        group = groups.setdefault(
            key,
            {
                "bets": 0,
                "won": 0,
                "lost": 0,
                "pending": 0,
                "stake": 0.0,
                "settled_stake": 0.0,
                "payout": 0.0,
                "coefficients": [],
            },
        )
        group["bets"] += 1
        group["stake"] += bet.stake
        group["coefficients"].append(bet.coefficient)
        if bet.status == "won":
            group["won"] += 1
            group["settled_stake"] += bet.stake
            group["payout"] += bet.payout
        elif bet.status == "lost":
            group["lost"] += 1
            group["settled_stake"] += bet.stake
        elif bet.status == "push":
            group["settled_stake"] += bet.stake
            group["payout"] += bet.payout
        elif bet.status == "pending":
            group["pending"] += 1

    rows: list[dict] = []
    for name, group in groups.items():
        decided = group["won"] + group["lost"]
        profit = group["payout"] - group["settled_stake"]
        rows.append(
            {
                "name": name,
                "bets": group["bets"],
                "won": group["won"],
                "lost": group["lost"],
                "pending": group["pending"],
                "stake": _round(group["stake"]),
                "payout": _round(group["payout"]),
                "profit": _round(profit),
                "win_rate_percent": _percent(group["won"], decided),
                "avg_coefficient": _round(
                    sum(group["coefficients"]) / len(group["coefficients"])
                )
                if group["coefficients"]
                else 0.0,
            }
        )
    rows.sort(key=lambda row: (-row["profit"], -row["bets"]))
    return rows


def _coefficient_analysis(bets: list[Bet]) -> list[dict]:
    rows: list[dict] = []
    for label, low, high in COEFFICIENT_BUCKETS:
        group = [bet for bet in bets if low <= bet.coefficient < high or (low <= bet.coefficient and high == float("inf"))]
        won = [bet for bet in group if bet.status == "won"]
        lost = [bet for bet in group if bet.status == "lost"]
        stake = sum(bet.stake for bet in group if bet.status in {"won", "lost"})
        payout = sum(bet.payout for bet in won)
        rows.append(
            {
                "name": label,
                "bets": len(group),
                "won": len(won),
                "lost": len(lost),
                "profit": _round(payout - stake),
                "win_rate_percent": _percent(len(won), len(won) + len(lost)),
            }
        )
    return rows


def _weekday_profile(bets: list[Bet]) -> list[dict]:
    buckets: dict[int, dict[str, float]] = defaultdict(lambda: {"bets": 0, "profit": 0.0, "stake": 0.0})
    for bet in bets:
        day = timeutil.local_date(bet.created_at)
        if day is None:
            continue
        bucket = buckets[day.weekday()]
        bucket["bets"] += 1
        bucket["stake"] += bet.stake
        if bet.status == "won":
            bucket["profit"] += bet.payout - bet.stake
        elif bet.status == "lost":
            bucket["profit"] -= bet.stake
    return [
        {
            "name": WEEKDAYS[index],
            "bets": int(buckets[index]["bets"]) if index in buckets else 0,
            "stake": _round(buckets[index]["stake"]) if index in buckets else 0.0,
            "profit": _round(buckets[index]["profit"]) if index in buckets else 0.0,
        }
        for index in range(7)
    ]


def summary(
    db: Session,
    *,
    preset: str | None = "30d",
    date_from: date | None = None,
    date_to: date | None = None,
    sport: str | None = None,
    source_id: int | None = None,
) -> dict[str, Any]:
    """Полная сводка статистики за период."""
    start, end = timeutil.resolve_range(preset, date_from, date_to)
    bets = fetch_bets(db, date_from=start, date_to=end, sport=sport, source_id=source_id)

    counts = _counts(bets)
    amounts = _amounts(bets)
    metrics = _metrics(bets, counts, amounts)
    timeline = _timeline(bets, start, end)
    drawdown = _drawdown(timeline)
    metrics["cumulative_roi_percent"] = _percent(metrics["profit"], amounts["settled_stake"])

    return {
        "range": {
            "preset": preset or "custom",
            "from": timeutil.local_date_str(start),
            "to": timeutil.local_date_str(end),
            "has_bounds": start is not None and end is not None,
        },
        "filters": {"sport": sport or "all", "source_id": source_id},
        "counts": counts,
        "amounts": amounts,
        "metrics": metrics,
        "drawdown": drawdown,
        "streaks": _streaks(bets),
        "timeline": timeline,
        "by_sport": _group_rows(bets, lambda bet: bet.sport),
        "by_source": _group_rows(bets, lambda bet: bet.source_name or "Без источника"),
        "by_month": _monthly_rows(bets),
        "by_status": [
            {
                "status": status,
                "name": STATUS_LABELS.get(status, status),
                "bets": sum(1 for bet in bets if bet.status == status),
                "stake": _round(sum(bet.stake for bet in bets if bet.status == status)),
            }
            for status in ("pending", "won", "lost", "push", "cancelled")
        ],
        "coefficients": _coefficient_analysis(bets),
        "weekdays": _weekday_profile(bets),
        "generated_at": timeutil.now_utc(),
    }


def _snapshot(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Ключевые метрики сводки для сравнения периодов."""
    if data is None:
        return None
    metrics = data["metrics"]
    counts = data["counts"]
    return {
        "profit": metrics["profit"],
        "roi_percent": metrics["roi_percent"],
        "win_rate_percent": metrics["win_rate_percent"],
        "avg_coefficient": metrics["avg_coefficient"],
        "turnover": metrics["turnover"],
        "max_drawdown": data["drawdown"]["max_drawdown"],
        "total": counts["total"],
        "won": counts["won"],
        "lost": counts["lost"],
    }


COMPARE_FIELDS = (
    "profit",
    "roi_percent",
    "win_rate_percent",
    "avg_coefficient",
    "turnover",
    "max_drawdown",
    "total",
    "won",
    "lost",
)


def compare(
    db: Session,
    *,
    preset: str | None = "30d",
    date_from: date | None = None,
    date_to: date | None = None,
    sport: str | None = None,
    source_id: int | None = None,
) -> dict[str, Any]:
    """Сравнить текущий период с предыдущим такой же длительности.

    Предыдущий период вычисляется от начала текущего (сдвиг назад на длину
    периода). Для периода «всё время» (без границ) предыдущий период не
    определяется — возвращается только текущий срез.
    """
    start, end = timeutil.resolve_range(preset, date_from, date_to)
    current = summary(
        db, preset=preset, date_from=date_from, date_to=date_to, sport=sport, source_id=source_id
    )

    previous = None
    prev_from: date | None = None
    prev_to: date | None = None
    start_day = timeutil.local_date(start)
    end_day = timeutil.local_date(end)
    if start_day is not None and end_day is not None:
        length = (end_day - start_day).days + 1
        prev_to = start_day - timedelta(days=1)
        prev_from = prev_to - timedelta(days=length - 1)
        previous = summary(
            db,
            preset="custom",
            date_from=prev_from,
            date_to=prev_to,
            sport=sport,
            source_id=source_id,
        )

    current_snapshot = _snapshot(current)
    previous_snapshot = _snapshot(previous)
    delta: dict[str, float] = {}
    for field in COMPARE_FIELDS:
        base = previous_snapshot[field] if previous_snapshot else 0
        diff = current_snapshot[field] - base
        delta[field] = int(diff) if field in {"total", "won", "lost"} else _round(diff)

    return {
        "range": {
            "preset": preset or "custom",
            "from": current["range"]["from"],
            "to": current["range"]["to"],
            "previous_from": prev_from.isoformat() if prev_from else None,
            "previous_to": prev_to.isoformat() if prev_to else None,
            "has_previous": previous is not None,
        },
        "filters": current["filters"],
        "current": current_snapshot,
        "previous": previous_snapshot,
        "delta": delta,
    }


def options(db: Session) -> dict[str, Any]:
    """Данные для фильтров интерфейса и подсказки о доступных периодах."""
    from app.models import Source
    from app.services.bets_service import available_sports

    bounds = db.execute(
        select(func.min(Bet.created_at), func.max(Bet.created_at), func.count(Bet.id))
    ).one()
    sources = [
        {"id": row.id, "name": row.name, "enabled": row.enabled}
        for row in db.execute(select(Source).order_by(Source.name)).scalars()
    ]
    return {
        "sports": available_sports(db),
        "sources": sources,
        "date_min": timeutil.local_date_str(bounds[0]),
        "date_max": timeutil.local_date_str(bounds[1]),
        "bets_count": int(bounds[2] or 0),
        "settled_statuses": list(SETTLED_STATUSES),
        "statuses": [
            {"value": key, "label": label} for key, label in STATUS_LABELS.items()
        ],
    }
