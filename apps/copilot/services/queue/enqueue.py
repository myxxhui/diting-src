"""任务入队 · Cron / API 轻量 enqueue。

[Ref: 29_ §2 · §4.1]
"""
from __future__ import annotations

import logging
from typing import Any

from arq import create_pool

from apps.copilot.services.queue.settings import redis_settings

logger = logging.getLogger(__name__)

_pool: Any = None


async def get_arq_pool():
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


async def close_arq_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def enqueue_executing_job(
    job_id: str,
    *,
    symbol: str | None = None,
    source: str = "cron",
) -> str:
    """CronJob / bootstrap 入队 executing_t0 job。"""
    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "collect_executing_job",
        job_id,
        symbol,
        source,
        _job_id=f"executing:{job_id}:{symbol or '*'}",
    )
    jid = job.job_id if job else ""
    logger.info("已入队 executing job_id=%s symbol=%s arq_job=%s", job_id, symbol, jid)
    return jid


async def enqueue_radar_job(
    job_id: str,
    *,
    symbol: str | None = None,
    source: str = "cron",
) -> str:
    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "collect_radar_job",
        job_id,
        symbol,
        source,
        _job_id=f"radar:{job_id}:{symbol or '*'}",
    )
    jid = job.job_id if job else ""
    logger.info("已入队 radar job_id=%s symbol=%s arq_job=%s", job_id, symbol, jid)
    return jid


async def enqueue_smoke_ping(message: str = "infra-check") -> str:
    pool = await get_arq_pool()
    job = await pool.enqueue_job("smoke_ping", message)
    return job.job_id if job else ""
