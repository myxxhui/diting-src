"""ExitEngine 编排 API。

[Ref: 03_/04_维度四/.../step_07_冲突处理与回测.md §7.1 E]
"""
from __future__ import annotations

from collections.abc import Generator
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.services.exit_engine_orchestrator import ExitEngineOrchestrator
from apps.exit_engine.services.portfolio_service import PortfolioService

router = APIRouter(prefix="/api/engine", tags=["engine"])


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class EvaluateBody(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)
    context_by_symbol: dict[str, dict[str, Any]] = Field(default_factory=dict)
    publish: bool = True
    user_id: str = "default"


def _result_to_dict(result) -> dict[str, Any]:
    return {
        "position_id": result.position_id,
        "symbol": result.symbol,
        "triggered_protocols": result.triggered_protocols,
        "published": result.published,
        "stream_msg_id": result.stream_msg_id,
        "conflict_audit_id": result.conflict_audit_id,
        "winner": result.winner.to_stream_dict() if result.winner else None,
        "evaluations": [
            {
                "protocol": e.protocol_name,
                "triggered": e.triggered,
                "audit_id": e.audit_id,
                "buffer_enqueued": e.buffer_enqueued,
            }
            for e in result.evaluations
        ],
    }


@router.post("/evaluate/{user_id}")
def evaluate_user(user_id: str, body: EvaluateBody, db: Session = Depends(get_db)):
    portfolio = PortfolioService(db).get_portfolio(user_id=user_id)
    if not portfolio.positions:
        raise HTTPException(status_code=404, detail=f"user {user_id} 无 active 持仓")
    orch = ExitEngineOrchestrator(db, publish=body.publish)
    results = orch.evaluate_portfolio(
        portfolio,
        context_by_symbol=body.context_by_symbol or {},
        user_id=user_id,
    )
    return {
        "user_id": user_id,
        "results": [_result_to_dict(r) for r in results],
        "published_count": sum(1 for r in results if r.published),
    }


@router.post("/evaluate/{user_id}/{position_id}")
def evaluate_position(
    user_id: str,
    position_id: str,
    body: EvaluateBody,
    db: Session = Depends(get_db),
):
    repo = HoldingsRepository(db)
    pos = repo.get(position_id)
    if pos is None or pos.user_id != user_id:
        raise HTTPException(status_code=404, detail=f"position {position_id} not found")
    portfolio = PortfolioService(db).get_portfolio(user_id=user_id)
    orch = ExitEngineOrchestrator(db, publish=body.publish)
    result = orch.evaluate_position(pos, portfolio, context=body.context, user_id=user_id)
    return _result_to_dict(result)
