"""阻塞等待 Redis 就绪（planning / step12 不跳过 Redis）。

[Ref: 24_行情解析与规划工作台_需求实现表.md]
"""
from __future__ import annotations

import logging
import time
from typing import Any

import redis

from apps.copilot.config import settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 120.0
DEFAULT_POLL_INTERVAL_SEC = 2.0


def wait_for_sync_redis(
    *,
    url: str | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
) -> redis.Redis:
    """轮询直到 Redis PONG；超时抛 TimeoutError。"""
    target = url or settings.redis_url
    deadline = time.monotonic() + timeout_sec
    last_err: Exception | None = None
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            client = redis.from_url(
                target,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            client.ping()
            if attempt > 1:
                logger.info("Redis 就绪 (%s) 第 %d 次尝试", target, attempt)
            return client
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt == 1 or attempt % 5 == 0:
                logger.warning(
                    "等待 Redis… (%s) attempt=%d err=%s",
                    target,
                    attempt,
                    exc,
                )
            time.sleep(poll_interval_sec)
    raise TimeoutError(
        f"Redis 在 {timeout_sec:.0f}s 内未就绪 ({target}): {last_err}"
    )


def wait_for_sync_redis_optional(
    *,
    url: str | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> Any:
    """测试夹具可 patch 的别名。"""
    return wait_for_sync_redis(url=url, timeout_sec=timeout_sec)
