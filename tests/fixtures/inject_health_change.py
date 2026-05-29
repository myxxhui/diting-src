"""TEST_ONLY：向 Redis 注入 health_change 事件（仅 pytest / 联调脚本）。"""
from __future__ import annotations

import json
import uuid
from typing import Any, Optional

import redis


def inject_health_change(
    redis_url: str,
    *,
    symbol: str = "002837",
    new_state: str = "exit",
    narrative_label: str = "",
    narrative_invalid_count: int = 0,
    stream: str = "events:monitor:health_change",
) -> str:
    client = redis.from_url(redis_url, decode_responses=True)
    event_id = f"hc-fix-{uuid.uuid4().hex[:10]}"
    payload: dict[str, Any] = {
        "symbol": symbol,
        "new_state": new_state,
        "narrative_label": narrative_label,
        "narrative_invalid_count": narrative_invalid_count,
        "event_id": event_id,
    }
    msg_id: str = client.xadd(stream, {"json": json.dumps(payload, ensure_ascii=False)})
    return msg_id
