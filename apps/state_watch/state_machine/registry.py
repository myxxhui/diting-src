"""状态机注册表(SQLite 持久 + Redis 缓存).

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

import json
from typing import Optional

import redis.asyncio as redis_async
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.state_watch.db.models import HoldingState
from apps.state_watch.state_machine.states import NodeState

_CACHE_KEY_PREFIX = "state_watch:node:"


def _cache_key(node_id: str) -> str:
    return f"{_CACHE_KEY_PREFIX}{node_id}"


async def register_node(
    session: AsyncSession,
    redis_client: redis_async.Redis,
    *,
    symbol: str,
    name: str,
    thesis_id: str,
    thesis_summary: str,
    slis: Optional[list] = None,
) -> HoldingState:
    holding = HoldingState(
        symbol=symbol,
        name=name,
        thesis_id=thesis_id,
        thesis_summary=thesis_summary,
        state=NodeState.GROWING.value,
        health_score=100.0,
        push_level=0,
        slis=slis or [],
    )
    session.add(holding)
    await session.commit()
    await session.refresh(holding)
    await _write_cache(redis_client, holding)
    return holding


async def _write_cache(redis_client: redis_async.Redis, holding: HoldingState) -> None:
    payload = {
        "id": holding.id,
        "symbol": holding.symbol,
        "name": holding.name,
        "state": holding.state,
        "health_score": holding.health_score,
        "push_level": holding.push_level,
        "updated_at": holding.updated_at.isoformat() if holding.updated_at else None,
    }
    try:
        await redis_client.set(
            _cache_key(holding.id), json.dumps(payload, ensure_ascii=False), ex=3600
        )
    except Exception:
        return


async def get_node(
    session: AsyncSession,
    redis_client: redis_async.Redis,
    node_id: str,
) -> Optional[HoldingState]:
    stmt = select(HoldingState).where(HoldingState.id == node_id)
    result = await session.execute(stmt)
    holding = result.scalar_one_or_none()
    if holding is not None:
        await _write_cache(redis_client, holding)
    return holding


async def list_active_nodes(session: AsyncSession) -> list[HoldingState]:
    stmt = select(HoldingState).where(HoldingState.state != NodeState.EXIT.value)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_by_symbol(session: AsyncSession, symbol: str) -> list[HoldingState]:
    stmt = select(HoldingState).where(HoldingState.symbol == symbol)
    result = await session.execute(stmt)
    return list(result.scalars().all())
