"""SP3 / SP5 扩展评估与 SP5 recent API。"""
from __future__ import annotations

import json
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.models.event_log import EventLogORM
from apps.exit_engine.protocols.sp5_financial_window import Sp5FinancialWindowProtocol
from apps.exit_engine.protocols.thesis_invalid import ThesisInvalidProtocol
from apps.exit_engine.services.stream_consumer import (
    HEALTH_CHANGE_STREAM,
    TIMER_SIGNAL_STREAM,
    process_health_change,
    process_timer_signal,
)

router = APIRouter(prefix="/api/protocols", tags=["protocols-ext"])


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Sp3EvaluateBody(BaseModel):
    symbol: str
    new_state: str = ""
    narrative_label: str = ""
    narrative_invalid_count: int = 0
    health_change_event_id: str = ""


class Sp5EvaluateBody(BaseModel):
    symbol: str
    stage: str = Field(description="left_accumulate | main_wave | retreat")
    evidence_url: str = ""
    financial_report_date: str = ""
    timer_signal_event_id: str = ""


def _position_from_symbol(db: Session, symbol: str):
    repo = HoldingsRepository(db)
    for p in repo.list_active():
        if p.symbol == symbol:
            return p
    # 联调：无持仓时用虚拟 position
    from apps.exit_engine.models.position import Position

    return Position(
        id=f"pos-{symbol}",
        symbol=symbol,
        name=symbol,
        quantity=100,
        cost_price=10.0,
        current_price=10.0,
    )


@router.post("/SP3/evaluate")
def evaluate_sp3(body: Sp3EvaluateBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    pos = _position_from_symbol(db, body.symbol)
    proto = ThesisInvalidProtocol()
    ctx = body.model_dump()
    check = proto.check(pos, ctx)
    if not check.triggered:
        return {"protocol": "SP3", "triggered": False, "check": check.context}
    signal = proto.trigger(pos, check)
    event = proto.output_event(signal)
    return {
        "protocol": "SP3",
        "triggered": True,
        "advice": signal.advice,
        "event": event.to_stream_dict(),
    }


@router.post("/SP5/evaluate")
def evaluate_sp5(body: Sp5EvaluateBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    pos = _position_from_symbol(db, body.symbol)
    proto = Sp5FinancialWindowProtocol()
    ctx = body.model_dump()
    check = proto.check(pos, ctx)
    if not check.triggered:
        return {"protocol": "SP5", "triggered": False, "check": check.context}
    signal = proto.trigger(pos, check)
    event = proto.output_event(signal)
    return {
        "protocol": "SP5",
        "triggered": True,
        "advice": signal.advice,
        "stage": check.context.get("stage"),
        "event": event.to_stream_dict(),
    }


@router.get("/SP5/recent")
def sp5_recent(days: int = 7, db: Session = Depends(get_db)) -> dict[str, Any]:
    """最近 N 日 SP5 相关 event_logs（供 D0 alerts 渲染）。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.scalars(
        select(EventLogORM)
        .where(
            EventLogORM.stream_key == TIMER_SIGNAL_STREAM,
            EventLogORM.handled.is_(True),
            EventLogORM.created_at >= since,
        )
        .order_by(EventLogORM.id.desc())
        .limit(50)
    ).all()
    advices = []
    proto = Sp5FinancialWindowProtocol()
    for row in rows:
        try:
            payload = json.loads(row.payload)
        except json.JSONDecodeError:
            continue
        stage = payload.get("stage", "")
        pos = _position_from_symbol(db, payload.get("symbol", ""))
        check = proto.check(pos, {"stage": stage, **payload})
        if check.triggered:
            sig = proto.trigger(pos, check)
            advices.append(
                {
                    "msg_id": row.msg_id,
                    "symbol": payload.get("symbol"),
                    "stage": check.context.get("stage"),
                    "advice": sig.advice,
                    "execute_mode": "advisory",
                }
            )
    return {"days": days, "count": len(advices), "advices": advices}


@router.post("/SP3/consume-once")
def sp3_consume_once(body: Sp3EvaluateBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    """TEST_ONLY / 联调：模拟 health_change 消费一次。"""
    payload = body.model_dump()
    payload["symbol"] = body.symbol
    result = process_health_change(db, payload, msg_id=body.health_change_event_id or "manual-sp3")
    return {
        "handled": result.handled,
        "triggered": result.triggered,
        "protocol": result.protocol,
        "reason": result.reason,
        "event": result.event.to_stream_dict() if result.event else None,
    }


@router.post("/SP5/consume-once")
def sp5_consume_once(body: Sp5EvaluateBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    payload = body.model_dump()
    payload["symbol"] = body.symbol
    result = process_timer_signal(db, payload, msg_id=body.timer_signal_event_id or "manual-sp5")
    return {
        "handled": result.handled,
        "triggered": result.triggered,
        "protocol": result.protocol,
        "reason": result.reason,
        "event": result.event.to_stream_dict() if result.event else None,
    }
