"""market_phase 切换事件 → Redis Stream（D0 邮件 / D4 候选）."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as redis_async

from apps.state_watch.config import settings

logger = logging.getLogger(__name__)

MARKET_PHASE_CHANGE_STREAM = "events:monitor:market_phase_change"


def _event_id() -> str:
    return f"mp-{uuid.uuid4().hex[:12]}"


async def publish_market_phase_change(
    redis_client: redis_async.Redis,
    *,
    symbol: str,
    name: str,
    prev_phase: str | None,
    new_phase: str,
    confidence: float,
    reasoning_tags: list[str],
    rule_signals: dict | None = None,
) -> Optional[str]:
    if prev_phase == new_phase:
        return None
    event_id = _event_id()
    payload = {
        "event_id": event_id,
        "event_type": "market_phase_change",
        "symbol": symbol,
        "name": name,
        "prev_market_phase": prev_phase or "",
        "market_phase": new_phase,
        "market_phase_confidence": confidence,
        "reasoning_tags": reasoning_tags,
        "rule_signals": rule_signals or {},
        "emitted_at": datetime.now(timezone.utc).isoformat(),
        "advice": _phase_advice(prev_phase, new_phase),
    }
    try:
        msg_id = await redis_client.xadd(
            MARKET_PHASE_CHANGE_STREAM,
            {"json": json.dumps(payload, ensure_ascii=False, default=str)},
        )
        logger.info(
            "market_phase_change %s %s→%s conf=%.2f msg=%s",
            symbol,
            prev_phase,
            new_phase,
            confidence,
            msg_id,
        )
        return msg_id
    except Exception as exc:
        logger.warning("market_phase_change publish failed: %s", exc)
        return None


def _phase_advice(prev: str | None, new: str) -> str:
    if new == "exhaustion":
        return "进入利好透支区，建议人工评估止盈或减仓"
    if new == "realization" and prev in ("concept", "expectation", ""):
        return "进入业绩兑现期，关注财报与量价共振"
    if new == "expectation" and prev == "concept":
        return "进入炒预期阶段，可关注加仓时机（需结合 thesis）"
    return f"市场阶段切换：{prev or '未知'} → {new}"
