"""协议评估路由(单协议)。

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_03_SP1止损协议.md]
"""
from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.protocol_config import load_sp1_config
from apps.exit_engine.protocols.stop_loss import StopLossProtocol
from apps.exit_engine.protocols.take_profit import TakeProfitProtocol
from apps.exit_engine.services.protocol_runner import evaluate_and_audit, evaluate_with_buffer

router = APIRouter(prefix="/api/protocols", tags=["protocols"])


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


PROTOCOL_BY_NAME = {
    "stop_loss": StopLossProtocol,
    "take_profit": TakeProfitProtocol,
}


@router.get("/SP1/preview")
@router.get("/stop_loss/preview")
def preview_sp1():
    """返回 yaml 驱动的 SP1 阈值与模板摘要."""
    cfg = load_sp1_config()
    return {
        "protocol_id": "SP1",
        "name": "stop_loss",
        "config": cfg,
        "trigger_rule": "(current_price / cost_price - 1) <= threshold",
    }


@router.post("/{name}/evaluate/{position_id}")
def evaluate_protocol(name: str, position_id: str, db: Session = Depends(get_db)):
    cls = PROTOCOL_BY_NAME.get(name)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"protocol {name} not implemented yet")
    repo = HoldingsRepository(db)
    pos = repo.get(position_id)
    if pos is None:
        raise HTTPException(status_code=404, detail=f"position {position_id} not found")
    protocol = cls(config=load_sp1_config() if name == "stop_loss" else None)
    if name == "take_profit":
        result = evaluate_with_buffer(protocol, pos, session=db)
    else:
        result = evaluate_and_audit(protocol, pos, session=db)
    return {
        "protocol": result.protocol_name,
        "triggered": result.triggered,
        "audit_id": result.audit_id,
        "event": result.event.to_stream_dict() if result.event else None,
        "signal": {
            "trigger_price": result.signal.trigger_price,
            "current_price": result.signal.current_price,
            "sell_ratio": result.signal.sell_ratio,
            "reason": result.signal.reason,
            "advice": result.signal.advice,
        }
        if result.signal
        else None,
    }
