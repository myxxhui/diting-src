"""全 active 分类 + 落库 + phase 切换事件."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis_async
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.common.holdings_sot import load_holdings_sot
from apps.state_watch.config import settings
from apps.state_watch.db.models import HoldingState, MarketPhaseRecord
from apps.state_watch.db.session import init_db, session_ctx
from apps.state_watch.market_phase.phase_change_publisher import publish_market_phase_change
from apps.state_watch.market_phase.rule_classifier_v1 import classify
from apps.state_watch.market_phase.schemas import ClassificationResult, MarketPhase
from apps.state_watch.market_phase.signal_builder import build_signals
from apps.state_watch.state_machine.states import NodeState

logger = logging.getLogger(__name__)


async def _ensure_holding(session: AsyncSession, symbol: str, name: str) -> HoldingState:
    sym = symbol.zfill(6)[-6:]
    row = await session.scalar(select(HoldingState).where(HoldingState.symbol == sym))
    if row:
        return row
    holding = HoldingState(
        symbol=sym,
        name=name or sym,
        thesis_id=f"sot-{sym}",
        thesis_summary=f"SoT 启动期 {sym}",
        state=NodeState.GROWING.value,
        health_score=100.0,
        push_level=0,
        slis=[],
    )
    session.add(holding)
    await session.flush()
    return holding


async def classify_symbol(
    session: AsyncSession,
    symbol: str,
    *,
    name: str = "",
    redis_client: redis_async.Redis | None = None,
    publish: bool = True,
) -> ClassificationResult:
    sot = load_holdings_sot()
    entry = sot.by_symbol(symbol) or sot.by_symbol(symbol.zfill(6))
    if entry is None:
        from apps.common.holdings_sot import HoldingEntry

        entry = HoldingEntry(symbol=symbol.zfill(6)[-6:], name=name or symbol, active=True)
    signals = await build_signals(entry)
    result = classify(signals)

    holding = await _ensure_holding(session, result.symbol, entry.name or name)
    prev = (holding.context or {}).get("market_phase")
    now = datetime.now(timezone.utc)

    record = MarketPhaseRecord(
        symbol=result.symbol,
        classified_at=now,
        market_phase=result.market_phase.value,
        confidence=result.confidence,
        reasoning_tags=result.reasoning_tags,
        rule_signals=result.rule_signals,
        classifier_version=result.classifier_version,
    )
    session.add(record)

    ctx = dict(holding.context or {})
    ctx["market_phase"] = result.market_phase.value
    ctx["market_phase_confidence"] = result.confidence
    ctx["market_phase_updated_at"] = now.isoformat()
    ctx["market_phase_reasoning"] = result.reasoning_tags
    if prev == MarketPhase.REALIZATION.value:
        ctx["last_realization_at"] = now.isoformat()
    holding.context = ctx
    holding.updated_at = now.replace(tzinfo=None)

    if publish and redis_client is not None and prev != result.market_phase.value:
        await publish_market_phase_change(
            redis_client,
            symbol=result.symbol,
            name=holding.name,
            prev_phase=prev,
            new_phase=result.market_phase.value,
            confidence=result.confidence,
            reasoning_tags=result.reasoning_tags,
            rule_signals=result.rule_signals,
        )

    return result


async def classify_all_active(*, publish: bool = True) -> dict[str, Any]:
    await init_db()
    sot = load_holdings_sot()
    redis_client = redis_async.from_url(settings.redis_url, decode_responses=True)
    results: list[dict[str, Any]] = []
    distribution: dict[str, int] = {p.value: 0 for p in MarketPhase}

    import os

    active = [e for e in sot.holdings if e.active]
    only = os.environ.get("MARKET_PHASE_SYMBOLS", "").strip()
    if only:
        wanted = {s.strip().zfill(6)[-6:] for s in only.split(",") if s.strip()}
        active = [e for e in active if e.symbol.zfill(6)[-6:] in wanted]

    async with session_ctx() as session:
        for entry in active:
            try:
                r = await classify_symbol(
                    session,
                    entry.symbol,
                    name=entry.name,
                    redis_client=redis_client if publish else None,
                    publish=publish,
                )
                distribution[r.market_phase.value] = distribution.get(r.market_phase.value, 0) + 1
                results.append(
                    {
                        "symbol": r.symbol,
                        "name": entry.name,
                        "market_phase": r.market_phase.value,
                        "confidence": r.confidence,
                        "reasoning_tags": r.reasoning_tags,
                    }
                )
            except Exception as exc:
                logger.exception("classify failed %s", entry.symbol)
                results.append({"symbol": entry.symbol, "error": str(exc)})
        await session.commit()

    await redis_client.aclose()
    return {
        "active_count": len(results),
        "distribution": distribution,
        "results": results,
    }


def phase_distribution_from_results(results: list[dict[str, Any]]) -> dict[str, int]:
    dist: dict[str, int] = {p.value: 0 for p in MarketPhase}
    for row in results:
        if "market_phase" in row:
            dist[row["market_phase"]] = dist.get(row["market_phase"], 0) + 1
    return dist
