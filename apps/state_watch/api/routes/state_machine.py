"""状态机 REST API.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.state_watch.db.session import get_session
from apps.state_watch.state_machine.registry import (
    get_node,
    list_active_nodes,
    list_by_symbol,
    register_node,
)

router = APIRouter(prefix="/api/state-machine", tags=["state-machine"])


class SLIInput(BaseModel):
    id: str
    name: str
    metric: str
    threshold: float
    operator: str = ">"
    weight: float = Field(default=1.0, ge=0, le=1)
    probe_type: str


class RegisterRequest(BaseModel):
    symbol: str
    name: str
    thesis_id: str
    thesis_summary: str
    slis: list[SLIInput] = Field(default_factory=list)


class NodeResponse(BaseModel):
    id: str
    symbol: str
    name: str
    state: str
    health_score: float
    push_level: int
    thesis_id: str


def _to_response(holding) -> NodeResponse:
    return NodeResponse(
        id=holding.id,
        symbol=holding.symbol,
        name=holding.name,
        state=holding.state,
        health_score=holding.health_score,
        push_level=holding.push_level,
        thesis_id=holding.thesis_id,
    )


@router.post("/register", response_model=NodeResponse)
async def register(
    payload: RegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> NodeResponse:
    holding = await register_node(
        session,
        request.app.state.redis,
        symbol=payload.symbol,
        name=payload.name,
        thesis_id=payload.thesis_id,
        thesis_summary=payload.thesis_summary,
        slis=[s.model_dump() for s in payload.slis],
    )
    return _to_response(holding)


@router.get("/list/active")
async def list_active(session: AsyncSession = Depends(get_session)) -> dict:
    nodes = await list_active_nodes(session)
    return {"count": len(nodes), "nodes": [_to_response(n).model_dump() for n in nodes]}


@router.get("/by-symbol/{symbol}")
async def by_symbol(symbol: str, session: AsyncSession = Depends(get_session)) -> dict:
    nodes = await list_by_symbol(session, symbol)
    return {"symbol": symbol, "nodes": [_to_response(n).model_dump() for n in nodes]}


@router.get("/{node_id}", response_model=NodeResponse)
async def get(
    node_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> NodeResponse:
    holding = await get_node(session, request.app.state.redis, node_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="node not found")
    return _to_response(holding)
