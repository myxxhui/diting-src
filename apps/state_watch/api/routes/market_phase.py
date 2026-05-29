"""market_phase API.

[Ref: 03_/.../step_09 §7.1-G]
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.common.holdings_sot import load_holdings_sot
from apps.state_watch.config import settings
from apps.state_watch.db.models import HoldingState, MarketPhaseRecord
from apps.state_watch.db.session import get_session
from apps.state_watch.market_phase.orchestrator import classify_all_active, classify_symbol
from apps.state_watch.market_phase.schemas import MarketPhase

router = APIRouter(prefix="/api/market-phase", tags=["market-phase"])


class ClassifyResponse(BaseModel):
    symbol: str
    market_phase: str
    confidence: float
    reasoning_tags: list[str] = Field(default_factory=list)
    classifier_version: str = "rule_v1"


class DistributionResponse(BaseModel):
    distribution: dict[str, int]
    total: int
    labels_zh: dict[str, str]


@router.post("/classify/{symbol}", response_model=ClassifyResponse)
async def classify_one(symbol: str, session: AsyncSession = Depends(get_session)):
    import redis.asyncio as redis_async

    sot = load_holdings_sot()
    entry = sot.by_symbol(symbol)
    if entry is None or not entry.active:
        raise HTTPException(404, detail=f"symbol {symbol} not in active SoT")
    redis_client = redis_async.from_url(settings.redis_url, decode_responses=True)
    try:
        result = await classify_symbol(
            session,
            symbol,
            name=entry.name,
            redis_client=redis_client,
            publish=True,
        )
        await session.commit()
    finally:
        await redis_client.aclose()
    return ClassifyResponse(
        symbol=result.symbol,
        market_phase=result.market_phase.value,
        confidence=result.confidence,
        reasoning_tags=result.reasoning_tags,
        classifier_version=result.classifier_version,
    )


@router.get("/distribution", response_model=DistributionResponse)
async def distribution(session: AsyncSession = Depends(get_session)):
    from apps.state_watch.market_phase.rules_config import load_rules

    labels = (load_rules().get("phase_labels_zh") or {}) if True else {}
    dist: dict[str, int] = {p.value: 0 for p in MarketPhase}
    rows = await session.scalars(select(HoldingState))
    total = 0
    for h in rows:
        phase = (h.context or {}).get("market_phase")
        if phase in dist:
            dist[phase] += 1
            total += 1
    return DistributionResponse(distribution=dist, total=total, labels_zh=labels)


@router.get("/history/{symbol}")
async def phase_history(symbol: str, limit: int = 20, session: AsyncSession = Depends(get_session)):
    sym = symbol.zfill(6)[-6:]
    stmt = (
        select(MarketPhaseRecord)
        .where(MarketPhaseRecord.symbol == sym)
        .order_by(MarketPhaseRecord.classified_at.desc())
        .limit(limit)
    )
    rows = (await session.scalars(stmt)).all()
    return [
        {
            "symbol": r.symbol,
            "market_phase": r.market_phase,
            "confidence": r.confidence,
            "reasoning_tags": r.reasoning_tags,
            "classified_at": r.classified_at.isoformat() if r.classified_at else None,
        }
        for r in rows
    ]
