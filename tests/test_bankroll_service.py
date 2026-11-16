"""Тесты банкролла: операции по счёту и расчёт текущего баланса."""

from __future__ import annotations

from app.schemas import BetCreate, CashFlowIn, CashFlowUpdate
from app.services import bankroll_service, bets_service, settings_service


def make_bet(db, **overrides):
    payload = {
        "sport": "Футбол",
        "event_name": "Зенит — Спартак",
        "coefficient": 2.0,
        "stake": 1000,
    }
    payload.update(overrides)
    return bets_service.create_bet(db, BetCreate(**payload))


def test_summary_is_empty_without_operations(db):
    summary = bankroll_service.summary(db)
    assert summary["balance"] == 0.0
    assert summary["operations"] == 0


def test_deposits_and_withdrawals_affect_balance(db):
    bankroll_service.create_cash_flow(db, CashFlowIn(kind="deposit", amount=5000))
    bankroll_service.create_cash_flow(db, CashFlowIn(kind="withdrawal", amount=2000))
    summary = bankroll_service.summary(db)
    assert summary["deposits"] == 5000.0
    assert summary["withdrawals"] == 2000.0
    assert summary["balance"] == 3000.0
    assert summary["operations"] == 2


def test_settled_bets_change_balance(db):
    won = make_bet(db, coefficient=2.0, stake=1000)
    bets_service.set_result(db, won, "won")
    lost = make_bet(db, stake=500)
    bets_service.set_result(db, lost, "lost")

    summary = bankroll_service.summary(db)
    assert summary["profit"] == 500.0  # +1000 за выигрыш, −500 за проигрыш
    assert summary["balance"] == 500.0


def test_pending_bet_stake_is_in_play(db):
    make_bet(db, stake=1500)

    summary = bankroll_service.summary(db)
    assert summary["in_play"] == 1500.0
    assert summary["balance"] == -1500.0
    assert summary["total"] == 0.0


def test_push_bet_returns_stake(db):
    bet = make_bet(db, stake=700)
    bets_service.set_result(db, bet, "push")

    summary = bankroll_service.summary(db)
    assert summary["profit"] == 0.0
    assert summary["balance"] == 0.0


def test_cancelled_bet_does_not_affect_balance(db):
    bet = make_bet(db, stake=2000)
    bets_service.set_result(db, bet, "cancelled")

    summary = bankroll_service.summary(db)
    assert summary["balance"] == 0.0
    assert summary["profit"] == 0.0


def test_cash_flow_update_and_delete(db):
    flow = bankroll_service.create_cash_flow(db, CashFlowIn(kind="deposit", amount=3000))
    updated = bankroll_service.update_cash_flow(
        db, flow, CashFlowUpdate(amount=4000, kind="withdrawal")
    )
    assert updated.amount == 4000.0
    assert updated.kind == "withdrawal"

    bankroll_service.delete_cash_flow(db, updated)
    items, total = bankroll_service.list_cash_flows(db)
    assert total == 0
    assert items == []


def test_list_cash_flows_orders_by_date_desc(db):
    from datetime import datetime, timezone

    bankroll_service.create_cash_flow(
        db, CashFlowIn(kind="deposit", amount=100, occurred_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    )
    bankroll_service.create_cash_flow(
        db, CashFlowIn(kind="withdrawal", amount=200, occurred_at=datetime(2024, 5, 1, tzinfo=timezone.utc))
    )

    items, total = bankroll_service.list_cash_flows(db)
    assert total == 2
    assert items[0].kind == "withdrawal"
    assert items[1].kind == "deposit"


# --- Кривая баланса, доходность и лимиты ------------------------------------
def test_balance_curve_tracks_days(db):
    from datetime import datetime, timezone

    bankroll_service.create_cash_flow(
        db,
        CashFlowIn(
            kind="deposit",
            amount=1000,
            occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )
    bet = make_bet(db, stake=400, created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    bets_service.set_result(db, bet, "lost")

    points = bankroll_service.balance_curve(db)
    assert points[0]["balance"] == 1000.0
    assert points[-1]["balance"] == 600.0
    # последняя точка кривой совпадает с текущим балансом сводки
    assert points[-1]["balance"] == bankroll_service.summary(db)["balance"]


def test_balance_curve_ignores_cancelled(db):
    from datetime import datetime, timezone

    bankroll_service.create_cash_flow(
        db,
        CashFlowIn(
            kind="deposit",
            amount=500,
            occurred_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        ),
    )
    bet = make_bet(db, stake=300, created_at=datetime(2026, 2, 2, tzinfo=timezone.utc))
    bets_service.set_result(db, bet, "cancelled")

    points = bankroll_service.balance_curve(db)
    assert points[-1]["balance"] == 500.0


def test_summary_yield_and_roi(db):
    from datetime import datetime, timezone

    bankroll_service.create_cash_flow(
        db,
        CashFlowIn(
            kind="deposit",
            amount=1000,
            occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )
    won = make_bet(db, coefficient=2.0, stake=100, created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    bets_service.set_result(db, won, "won")

    summary = bankroll_service.summary(db)
    assert summary["settled_stake"] == 100.0
    assert summary["yield_percent"] == 100.0  # профит 100 / оборот 100
    assert summary["roi_percent"] > 0


def test_summary_limits(db):
    settings_service.update_settings(
        db,
        {"bankroll_goal": 2000.0, "stop_loss_percent": 50.0, "max_stake_percent": 5.0},
    )
    bankroll_service.create_cash_flow(db, CashFlowIn(kind="deposit", amount=1000))

    limits = bankroll_service.summary(db)["limits"]
    assert limits["bankroll_goal"] == 2000.0
    assert limits["goal_progress_percent"] == 50.0
    assert limits["stop_loss_level"] == 500.0  # пик 1000 × (1 − 0.5)
    assert limits["max_stake_amount"] == 50.0  # 1000 × 5 %


def test_summary_limits_disabled_by_default(db):
    bankroll_service.create_cash_flow(db, CashFlowIn(kind="deposit", amount=1000))
    limits = bankroll_service.summary(db)["limits"]
    assert limits["bankroll_goal"] == 0.0
    assert limits["stop_loss_level"] == 0.0
    assert limits["max_stake_amount"] == 0.0
