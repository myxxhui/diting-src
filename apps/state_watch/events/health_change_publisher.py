"""D3 state_watch → Redis Stream：向 D4 exit_engine 发布 health_change 事件。

Stream key:  events:monitor:health_change
消费方:      D4 exit_engine SP3 ThesisInvalidProtocol

[Ref: 03_/03_维度三/.../step_07_health_change事件流与10持仓测试.md]
"""
from __future__ import annotations

import logging
from typing import Optional

import redis.asyncio as redis_async

from apps.state_watch.events.health_change import HealthChangeEvent
from apps.state_watch.events.publisher import HEALTH_CHANGE_STREAM
from apps.state_watch.health.push_level import health_to_push_level

logger = logging.getLogger(__name__)

__all__ = [
    "HEALTH_CHANGE_STREAM",
    "map_score_to_state",
    "publish_health_change",
]


def map_score_to_state(health_score: float) -> str:
    """依据 health_score 映射到状态标签（供 D4 SP3 判断）。"""
    if health_score < 30.0:
        return "exit"
    if health_score < 60.0:
        return "warning"
    return "growing"


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
    name: str = "",
) -> Optional[str]:
    """向 `events:monitor:health_change` Stream 写入一条健康变化事件。

    返回 XADD 消息 ID；失败返回 None（仅记录日志，不抛出）。
    """
    old_push = health_to_push_level(prev_score)
    new_push = health_to_push_level(health_score)
    event = HealthChangeEvent(
        symbol=symbol,
        name=name or symbol,
        node_id=symbol,
        old_state=map_score_to_state(prev_score) if new_state != "exit" else "warning",
        new_state=new_state,
        old_health=prev_score,
        new_health=health_score,
        old_push_level=old_push,
        new_push_level=new_push,
        reason=source_probe or "health_change",
        thesis_status="invalid" if new_state == "exit" else "valid",
        narrative_label=narrative_label,
        narrative_invalid_count=narrative_invalid_count,
    )
    if market_phase:
        event.sli_snapshot = [
            {
                "market_phase": market_phase,
                "market_phase_confidence": market_phase_confidence,
            }
        ]
    fields = event.to_redis_fields()
    try:
        msg_id = await redis_client.xadd(
            HEALTH_CHANGE_STREAM,
            fields,
            maxlen=10_000,
            approximate=True,
        )
        logger.info(
            "health_change published symbol=%s state=%s score=%.1f→%.1f msg_id=%s",
            symbol,
            new_state,
            prev_score,
            health_score,
            msg_id,
        )
        return msg_id if isinstance(msg_id, str) else msg_id.decode()
    except Exception as exc:
        logger.warning("health_change publish failed: %s", exc)
        return None
