"""向 Redis 注入 mock health_change 事件,本地无维度三时使用。

用法: python scripts/inject_mock_health_change.py 600519 -23 3

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_03]
"""
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone

import redis.asyncio as redis


async def main(symbol: str, delta: float, push_level: int) -> None:
    r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
    payload = {
        "event_id": str(uuid.uuid4()),
        "event_type": "health_change",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trace_id": str(uuid.uuid4()),
        "symbol": symbol,
        "name": f"mock-{symbol}",
        "old_health": 75.0,
        "new_health": 75.0 + delta,
        "health_delta": delta,
        "push_level": push_level,
        "change_reason": "mock 注入(本地测试)",
        "node_state": {"state": "warning" if push_level >= 2 else "stable"},
    }
    msg_id = await r.xadd("events:monitor:health_change", {"json": json.dumps(payload)})
    print(f"injected msg_id={msg_id} payload={payload}")
    await r.aclose()


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "600519"
    d = float(sys.argv[2]) if len(sys.argv) > 2 else -23.0
    pl = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    asyncio.run(main(sym, d, pl))
