"""探针心跳记录到 Redis(轻量 KV).

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_04_探针调度器与SLI聚合.md]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import redis.asyncio as redis_async

logger = logging.getLogger(__name__)

_KEY_PREFIX = "state_watch:probe:heartbeat:"


def _key(probe_type: str) -> str:
    return f"{_KEY_PREFIX}{probe_type}"


async def record(
    client: redis_async.Redis,
    probe_type: str,
    *,
    status: str,
    success_count: int,
    fail_count: int,
    last_error: str = "",
) -> None:
    payload: dict[str, Any] = {
        "probe_type": probe_type,
        "status": status,
        "success_count": success_count,
        "fail_count": fail_count,
        "last_error": last_error,
        "ts": datetime.utcnow().isoformat(),
    }
    try:
        await client.set(_key(probe_type), json.dumps(payload, ensure_ascii=False), ex=24 * 3600)
    except Exception as e:
        logger.warning("heartbeat record fail probe=%s err=%s", probe_type, e)


async def get_all(client: redis_async.Redis) -> list[dict]:
    out: list[dict] = []
    try:
        async for k in client.scan_iter(f"{_KEY_PREFIX}*"):
            raw = await client.get(k)
            if raw:
                out.append(json.loads(raw))
    except Exception as e:
        logger.warning("heartbeat get_all fail: %s", e)
    return out
