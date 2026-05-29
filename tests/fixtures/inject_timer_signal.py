"""TEST_ONLY：向 Redis 注入 timer_signal 事件（仅 pytest / 联调脚本）。"""
from __future__ import annotations

import json
import uuid
from typing import Any

import redis


def inject_timer_signal(
    redis_url: str,
    *,
    symbol: str = "300308",
    stage: str = "main_wave",
    thesis_card_id: str = "test-thesis",
    stream: str = "events:deep_strike:timer_signal",
) -> str:
    client = redis.from_url(redis_url, decode_responses=True)
    event_id = f"ts-fix-{uuid.uuid4().hex[:10]}"
    payload: dict[str, Any] = {
        "event_type": "timer_signal",
        "event_id": event_id,
        "thesis_card_id": thesis_card_id,
        "symbol": symbol,
        "stage": stage,
        "execute_mode": "advisory",
    }
    msg_id: str = client.xadd(stream, {"json": json.dumps(payload, ensure_ascii=False)})
    return msg_id
