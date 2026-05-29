"""探针 REST API.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_04_探针调度器与SLI聚合.md]
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.state_watch.db.models import HoldingState, NodeSLIValue
from apps.state_watch.db.session import get_session
from apps.state_watch.probes.event import EventProbe
from apps.state_watch.probes.financial import FinancialProbe
from apps.state_watch.probes.heartbeat import get_all as heartbeat_all
from apps.state_watch.probes.news import NewsProbe
from apps.state_watch.probes.price import PriceProbe

router = APIRouter(prefix="/api/probes", tags=["probes"])

_PROBES = {
    "financial": FinancialProbe(),
    "news": NewsProbe(),
    "price": PriceProbe(),
    "event": EventProbe(),
}


class TriggerRequest(BaseModel):
    probe_type: str


@router.post("/{node_id}/trigger")
async def trigger(
    node_id: str,
    payload: TriggerRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    if payload.probe_type not in _PROBES:
        raise HTTPException(status_code=400, detail=f"unknown probe_type {payload.probe_type}")
    stmt = select(HoldingState).where(HoldingState.id == node_id)
    res = await session.execute(stmt)
    node = res.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")
    probe = _PROBES[payload.probe_type]
    result = await probe.fetch(node.symbol)
    return {
        "node_id": node.id,
        "symbol": node.symbol,
        "probe_type": payload.probe_type,
        "result": result.to_dict(),
    }


@router.get("/{node_id}/status")
async def status(node_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    stmt = select(NodeSLIValue).where(NodeSLIValue.holding_id == node_id)
    res = await session.execute(stmt)
    rows = list(res.scalars().all())
    return {
        "node_id": node_id,
        "sli_count": len(rows),
        "items": [
            {
                "metric": r.metric,
                "probe_type": r.probe_type,
                "current_value": r.current_value,
                "last_score": r.last_score,
                "last_updated": r.last_updated.isoformat() if r.last_updated else None,
            }
            for r in rows
        ],
    }


@router.get("/heartbeat/all")
async def heartbeat_all_route(request: Request) -> dict:
    items = await heartbeat_all(request.app.state.redis)
    return {"count": len(items), "items": items}
