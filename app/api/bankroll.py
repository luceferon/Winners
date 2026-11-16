"""Маршруты раздела «Баланс»: операции по счёту и сводка по банкроллу."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CashFlow
from app.schemas import CashFlowIn, CashFlowOut, CashFlowUpdate
from app.services import bankroll_service

router = APIRouter(prefix="/api/bankroll", tags=["bankroll"])


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict:
    """Текущий баланс счёта и итоги операций."""
    return bankroll_service.summary(db)


@router.get("/curve")
def curve(db: Session = Depends(get_db)) -> dict:
    """Кривая баланса счёта по дням для графика."""
    return {"points": bankroll_service.balance_curve(db)}


@router.get("/operations")
def list_operations(
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Список операций пополнения и вывода средств."""
    items, total = bankroll_service.list_cash_flows(db, limit=limit, offset=offset)
    return {
        "items": [flow.as_dict() for flow in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/operations", response_model=CashFlowOut, status_code=201)
def create_operation(payload: CashFlowIn, db: Session = Depends(get_db)) -> CashFlow:
    """Добавить пополнение или вывод средств."""
    return bankroll_service.create_cash_flow(db, payload)


@router.put("/operations/{flow_id}", response_model=CashFlowOut)
def update_operation(
    flow_id: int, payload: CashFlowUpdate, db: Session = Depends(get_db)
) -> CashFlow:
    """Изменить операцию по счёту."""
    flow = db.get(CashFlow, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="Операция не найдена")
    return bankroll_service.update_cash_flow(db, flow, payload)


@router.delete("/operations/{flow_id}")
def delete_operation(flow_id: int, db: Session = Depends(get_db)) -> dict:
    """Удалить операцию по счёту."""
    flow = db.get(CashFlow, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="Операция не найдена")
    bankroll_service.delete_cash_flow(db, flow)
    return {"ok": True, "deleted": flow_id}
