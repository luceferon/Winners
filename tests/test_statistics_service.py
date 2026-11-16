"""Тесты агрегированной статистики."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Source
from app.schemas import BetCreate
from app.services import bets_service, statistics_service
from app.services.timeutil import now_utc


def make_source(db, name: str = "Тест") -> Source:
    source = Source(name=name)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def build_dataset(db):
    source = make_source(db)
    now = now_utc()

    won = bets_service.create_bet(
        db,
        BetCreate(
            sport="Футбол",
            event_name="Зенит — Спартак",
            coefficient=2.0,
            stake=1000,
            source_id=source.id,
            created_at=now - timedelta(days=1),
        ),
    )
    bets_service.set_result(db, won, "won")

    lost = bets_service.create_bet(
        db,
        BetCreate(
            sport="Футбол",
            event_name="ЦСКА — Локомотив",
            coefficient=1.5,
            stake=500,
            source_id=source.id,
            created_at=now - timedelta(days=2),
        ),
    )
    bets_service.set_result(db, lost, "lost")

    bets_service.create_bet(
        db,
        BetCreate(
            sport="Хоккей",
            event_name="СКА — ЦСКА",
            coefficient=3.0,
            stake=200,
            created_at=now - timedelta(hours=2),
        ),
    )
    return source


def test_summary_counts(db):
    build_dataset(db)
    summary = statistics_service.summary(db, preset="30d")
    counts = summary["counts"]
    assert counts["total"] == 3
    assert counts["won"] == 1
    assert counts["lost"] == 1
    assert counts["pending"] == 1


def test_summary_amounts(db):
    build_dataset(db)
    amounts = statistics_service.summary(db, preset="30d")["amounts"]
    assert amounts["won_stake"] == 1000.0
    assert amounts["lost_stake"] == 500.0
    assert amounts["active"] == 200.0
    assert amounts["staked_total"] == 1700.0


def test_summary_metrics(db):
    build_dataset(db)
    metrics = statistics_service.summary(db, preset="30d")["metrics"]
    # 2000 (выплата) - 1000 - 500 = 500
    assert metrics["profit"] == 500.0
    assert metrics["win_rate_percent"] == 50.0
    assert round(metrics["roi_percent"], 1) == 33.3


def test_summary_breakdowns(db):
    build_dataset(db)
    summary = statistics_service.summary(db, preset="30d")
    assert len(summary["by_status"]) == 5
    assert summary["by_sport"]
    assert summary["by_source"]
    assert summary["timeline"]
    assert summary["weekdays"] and len(summary["weekdays"]) == 7
    assert summary["coefficients"]


def test_summary_filter_by_sport(db):
    build_dataset(db)
    summary = statistics_service.summary(db, preset="30d", sport="Футбол")
    assert summary["counts"]["total"] == 2
    assert summary["counts"]["pending"] == 0


def test_summary_preset_all_includes_everything(db):
    build_dataset(db)
    summary = statistics_service.summary(db, preset="all")
    assert summary["counts"]["total"] == 3
    assert summary["range"]["preset"] == "all"


def test_options_returns_filters(db):
    source = build_dataset(db)
    options = statistics_service.options(db)
    assert "Футбол" in options["sports"]
    assert "Хоккей" in options["sports"]
    assert options["bets_count"] == 3
    assert any(item["name"] == source.name for item in options["sources"])
    assert options["date_min"] and options["date_max"]


def test_options_empty_db(db):
    options = statistics_service.options(db)
    assert options["sports"] == []
    assert options["bets_count"] == 0
    assert options["date_min"] is None


# --- Просадка, серии, разбивка по месяцам, сравнение периодов ---------------
def make_bet_on(
    db,
    days_ago: int,
    *,
    status: str = "pending",
    coefficient: float = 2.0,
    stake: float = 1000.0,
    name: str = "Событие",
):
    bet = bets_service.create_bet(
        db,
        BetCreate(
            sport="Футбол",
            event_name=f"{name} {days_ago}",
            coefficient=coefficient,
            stake=stake,
            created_at=now_utc() - timedelta(days=days_ago),
        ),
    )
    if status != "pending":
        bets_service.set_result(db, bet, status)
    return bet


def test_drawdown_metrics(db):
    make_bet_on(db, 4, status="lost", stake=500)  # накопленный −500
    make_bet_on(db, 3, status="lost", stake=300)  # накопленный −800
    make_bet_on(db, 2, status="won", coefficient=2.0, stake=400)  # +400 → −400

    summary = statistics_service.summary(db, preset="30d")
    assert summary["drawdown"]["peak_profit"] == 0.0
    assert summary["drawdown"]["max_drawdown"] == -800.0
    assert summary["drawdown"]["current_drawdown"] == -400.0
    # накопительный ROI доступен в последней точке динамики
    assert "cumulative_roi_percent" in summary["timeline"][-1]


def test_streaks(db):
    for index, status in enumerate(["won", "lost", "won", "won"]):
        make_bet_on(db, 10 - index, status=status)

    streaks = statistics_service.summary(db, preset="30d")["streaks"]
    assert streaks["max_win_streak"] == 2
    assert streaks["max_lose_streak"] == 1
    assert streaks["current_streak"] == 2
    assert streaks["current_streak_kind"] == "won"


def test_by_month_splits(db):
    bets_service.create_bet(
        db,
        BetCreate(
            sport="Футбол",
            event_name="Январь — Тур",
            coefficient=2.0,
            stake=1000,
            created_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        ),
    )
    bets_service.create_bet(
        db,
        BetCreate(
            sport="Футбол",
            event_name="Февраль — Тур",
            coefficient=2.0,
            stake=1000,
            created_at=datetime(2026, 2, 15, tzinfo=timezone.utc),
        ),
    )

    rows = statistics_service.summary(db, preset="all")["by_month"]
    assert [row["name"] for row in rows] == ["2026-01", "2026-02"]
    assert all("roi_percent" in row for row in rows)


def test_compare_delta(db):
    won = bets_service.create_bet(
        db,
        BetCreate(
            sport="Футбол",
            event_name="Текущий — Период",
            coefficient=2.0,
            stake=1000,
            created_at=now_utc() - timedelta(days=1),
        ),
    )
    bets_service.set_result(db, won, "won")
    lost = bets_service.create_bet(
        db,
        BetCreate(
            sport="Футбол",
            event_name="Прошлый — Период",
            coefficient=2.0,
            stake=200,
            created_at=now_utc() - timedelta(days=40),
        ),
    )
    bets_service.set_result(db, lost, "lost")

    result = statistics_service.compare(db, preset="30d")
    assert result["range"]["has_previous"] is True
    assert result["current"]["profit"] == 1000.0
    assert result["previous"]["profit"] == -200.0
    assert result["delta"]["profit"] == 1200.0
    assert result["delta"]["total"] == 0


def test_compare_all_time_has_no_previous(db):
    make_bet_on(db, 1, status="won")
    result = statistics_service.compare(db, preset="all")
    assert result["range"]["has_previous"] is False
    assert result["previous"] is None
    assert result["delta"]["profit"] == result["current"]["profit"]
