"""缓冲期挂起信号路由。

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_04_SP2止盈协议.md]
"""
from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.services.buffer_manager import BufferManager

router = APIRouter(prefix="/api/buffer", tags=["buffer"])


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class CancelRequest(BaseModel):
    reason: str = "manual"


@router.get("/pending")
def list_pending(
    position_id: str | None = None,
    protocol_name: str | None = None,
    user_id: str = "default",
    db: Session = Depends(get_db),
):
    pendings = BufferManager(db).list_pending(
        position_id=position_id,
        protocol_name=protocol_name,
        user_id=user_id,
    )
    return [
        {
            "audit_id": p.audit_id,
            "protocol": p.protocol_name,
            "symbol": p.symbol,
            "position_id": p.position_id,
            "trigger_price": p.trigger_price,
            "triggered_price": p.triggered_price,
            "sell_ratio": p.sell_ratio,
            "triggered_at": p.triggered_at.isoformat(),
            "buffer_end_at": p.buffer_end_at.isoformat(),
            "advice": p.advice,
        }
        for p in pendings
    ]


@router.post("/{audit_id}/cancel")
def cancel(audit_id: str, payload: CancelRequest, db: Session = Depends(get_db)):
    success = BufferManager(db).cancel(audit_id, reason=payload.reason)
    if not success:
        raise HTTPException(status_code=404, detail="audit_id 不存在或已结束")
    return {"success": True, "audit_id": audit_id}
