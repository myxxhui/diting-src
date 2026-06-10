"""ARQ Redis 连接配置。

[Ref: 29_ §4.3]
"""
from __future__ import annotations

import os

from arq.connections import RedisSettings


def arq_redis_dsn() -> str:
    return (
        os.environ.get("ARQ_REDIS_URL")
        or os.environ.get("COPILOT_ARQ_REDIS_URL")
        or _derive_from_copilot_redis()
    )


def _derive_from_copilot_redis() -> str:
    base = os.environ.get("COPILOT_REDIS_URL") or os.environ.get("REDIS_URL") or ""
    if not base:
        return "redis://127.0.0.1:6379/1"
    if base.rstrip("/").endswith("/0"):
        return base.rsplit("/", 1)[0] + "/1"
    if "/" not in base.split("://", 1)[-1]:
        return base.rstrip("/") + "/1"
    return base


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(arq_redis_dsn())


def max_jobs() -> int:
    return int(os.environ.get("ARQ_MAX_JOBS", "8"))


def retry_backoff() -> tuple[int, ...]:
    raw = os.environ.get("ARQ_RETRY_BACKOFF", "5,20,60")
    parts = [int(x.strip()) for x in raw.split(",") if x.strip()]
    return tuple(parts) if parts else (5, 20, 60)
