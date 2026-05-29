"""D3 state_watch → Redis Stream：向 D4 exit_engine 发布 health_change 事件。

Stream key:  events:monitor:health_change
消费方:      D4 exit_engine SP3 ThesisInvalidProtocol

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_05_NLI叙事一致性.md]
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as redis_async

logger = logging.getLogger(__name__)

HEALTH_CHANGE_STREAM = "events:monitor:health_change"


def _event_id() -> str:
    return f"hc-{uuid.uuid4().hex[:12]}"


async def publish_health_change(
    redis_client: redis_async.Redis,
    *,
    symbol: str,
    new_state: str,
    health_score: float,
    prev_score: float,
    narrative_label: str = "",
    narrative_invalid_count: int = 0,
    source_probe: str = "",
    market_phase: str = "",
    market_phase_confidence: float | None = None,
) -> Optional[str]:
    """向 `events:monitor:health_change` Stream 写入一条健康变化事件。

    返回 XADD 消息 ID；失败返回 None（仅记录日志，不抛出）。
    """
    event_id = _event_id()
    payload = {
        "event_id": event_id,
        "symbol": symbol,
        "new_state": new_state,
        "health_score": health_score,
        "prev_score": prev_score,
        "narrative_label": narrative_label,
        "narrative_invalid_count": narrative_invalid_count,
        "source_probe": source_probe,
        "market_phase": market_phase,
        "market_phase_confidence": market_phase_confidence,
        "emitted_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        msg_id = await redis_client.xadd(
            HEALTH_CHANGE_STREAM,
            {"json": json.dumps(payload, ensure_ascii=False, default=str)},
        )
        logger.info(
            "health_change published symbol=%s state=%s score=%.1f→%.1f msg_id=%s",
            symbol,
            new_state,
            prev_score,
            health_score,
            msg_id,
        )
        return msg_id
    except Exception as exc:
        logger.warning("health_change publish failed: %s", exc)
        return None


def map_score_to_state(health_score: float) -> str:
    """依据 health_score 映射到状态标签（供 D4 SP3 判断）。"""
    if health_score < 30.0:
        return "exit"
    if health_score < 60.0:
        return "warning"
    return "growing"
