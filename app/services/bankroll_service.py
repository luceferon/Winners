"""Банкролл: операции по счёту (пополнения/выводы) и расчёт текущего баланса."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Bet, CashFlow, utcnow
from app.schemas import CashFlowIn, CashFlowUpdate
from app.services import settings_service, timeutil

CASH_FLOW_KINDS = ("deposit", "withdrawal")


class BankrollError(ValueError):
    """Ошибка операций по счёту."""


def _percent(part: float, whole: float) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def list_cash_flows(
    db: Session, *, limit: int = 200, offset: int = 0
) -> tuple[list[CashFlow], int]:
    """Операции по счёту от новых к старым."""
    total = db.execute(select(func.count(CashFlow.id))).scalar_one()
    stmt = (
        select(CashFlow)
        .order_by(CashFlow.occurred_at.desc(), CashFlow.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all()), int(total)


def create_cash_flow(db: Session, payload: CashFlowIn) -> CashFlow:
    """Добавить операцию пополнения или вывода."""
    flow = CashFlow(
        kind=payload.kind,
        amount=float(payload.amount),
        occurred_at=payload.occurred_at or utcnow(),
        note=payload.note,
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)
    return flow


def update_cash_flow(db: Session, flow: CashFlow, payload: CashFlowUpdate) -> CashFlow:
    """Изменить существующую операцию."""
    data = payload.model_dump(exclude_unset=True)
    for field in ("kind", "amount", "occurred_at", "note"):
        if field in data and data[field] is not None:
            setattr(flow, field, data[field])
    db.commit()
    db.refresh(flow)
    return flow


def delete_cash_flow(db: Session, flow: CashFlow) -> None:
    """Удалить операцию по счёту."""
    db.delete(flow)
    db.commit()


def balance_curve(db: Session) -> list[dict[str, Any]]:
    """Кривая баланса по дням: «дата → средства на счёте».

    Учитываются операции по счёту и ставки: при постановке ставки сумма уходит
    со счёта (день создания), при расчёте возвращается выплата (день расчёта).
    Отменённые ставки не влияют на баланс. Последняя точка совпадает с текущим
    балансом из :func:`summary`.
    """
    events: dict[date, dict[str, float]] = defaultdict(
        lambda: {"flows": 0.0, "stake": 0.0, "payout": 0.0}
    )
    for flow in db.execute(select(CashFlow)).scalars():
        day = timeutil.local_date(flow.occurred_at)
        if day is None:
            continue
        events[day]["flows"] += flow.amount if flow.kind == "deposit" else -flow.amount

    for status, stake, payout, created_at, settled_at in db.execute(
        select(Bet.status, Bet.stake, Bet.payout, Bet.created_at, Bet.settled_at)
    ).all():
        if status == "cancelled":
            continue
        stake_value = float(stake or 0.0)
        created_day = timeutil.local_date(created_at)
        if created_day is not None:
            events[created_day]["stake"] += stake_value
        if status != "pending":
            settled_day = timeutil.local_date(settled_at) or created_day
            if settled_day is not None:
                events[settled_day]["payout"] += float(payout or 0.0)

    points: list[dict[str, Any]] = []
    balance = 0.0
    for day in sorted(events):
        bucket = events[day]
        delta = bucket["flows"] - bucket["stake"] + bucket["payout"]
        balance += delta
        points.append(
            {
                "date": day.isoformat(),
                "balance": round(balance, 2),
                "delta": round(delta, 2),
            }
        )
    return points


def summary(db: Session) -> dict[str, Any]:
    """Сводка по счёту: операции и текущие средства.

    Баланс считается как «деньги, которые лежат на счёте»:
    пополнения − выводы + результат рассчитанных ставок − суммы активных
    (ещё не рассчитанных) ставок. Ставки со статусом «отменена» не влияют на
    баланс, так как сумма возвращается игроку.
    """
    flows = list(db.execute(select(CashFlow)).scalars().all())
    deposits = round(sum(flow.amount for flow in flows if flow.kind == "deposit"), 2)
    withdrawals = round(sum(flow.amount for flow in flows if flow.kind == "withdrawal"), 2)

    staked = 0.0
    settled_stake = 0.0
    returned = 0.0
    in_play = 0.0
    profit = 0.0
    for status, stake, payout in db.execute(select(Bet.status, Bet.stake, Bet.payout)).all():
        stake = float(stake or 0.0)
        payout = float(payout or 0.0)
        if status == "won":
            staked += stake
            settled_stake += stake
            returned += payout
            profit += payout - stake
        elif status == "lost":
            staked += stake
            settled_stake += stake
            profit -= stake
        elif status == "push":
            staked += stake
            settled_stake += stake
            returned += payout
            profit += payout - stake
        elif status == "pending":
            staked += stake
            in_play += stake
        # cancelled: сумма возвращена — на баланс не влияет

    balance = deposits - withdrawals + profit - in_play
    curve = balance_curve(db)
    balances = [point["balance"] for point in curve]
    avg_balance = round(sum(balances) / len(balances), 2) if balances else 0.0
    peak_balance = round(max(balances), 2) if balances else 0.0

    goal = float(settings_service.get_setting(db, "bankroll_goal", 0.0) or 0.0)
    stop_loss_percent = float(settings_service.get_setting(db, "stop_loss_percent", 0.0) or 0.0)
    max_stake_percent = float(settings_service.get_setting(db, "max_stake_percent", 0.0) or 0.0)

    return {
        "deposits": deposits,
        "withdrawals": withdrawals,
        "staked": round(staked, 2),
        "settled_stake": round(settled_stake, 2),
        "returned": round(returned, 2),
        "in_play": round(in_play, 2),
        "profit": round(profit, 2),
        "balance": round(balance, 2),
        "total": round(balance + in_play, 2),
        "avg_balance": avg_balance,
        "peak_balance": peak_balance,
        # Yield — доходность на оборот, ROI — доходность на средний банкролл.
        "yield_percent": _percent(profit, settled_stake),
        "roi_percent": _percent(profit, avg_balance),
        "operations": len(flows),
        "currency": settings_service.get_setting(db, "currency", "RUB"),
        "limits": {
            "bankroll_goal": goal,
            "goal_progress_percent": _percent(balance, goal),
            "stop_loss_percent": stop_loss_percent,
            "stop_loss_level": round(peak_balance * (1 - stop_loss_percent / 100), 2)
            if stop_loss_percent
            else 0.0,
            "max_stake_percent": max_stake_percent,
            "max_stake_amount": round(balance * max_stake_percent / 100, 2)
            if max_stake_percent
            else 0.0,
        },
    }
