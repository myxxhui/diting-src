"""executing_t0 job 执行。

[Ref: 28_ §4.6]
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.jobs_registry import JOB_REGISTRY
from apps.copilot.modules.executing.orchestrator import (
    quote_intraday_job,
    run_daily_pipeline,
    run_t0_collect,
)
from apps.copilot.modules.executing.storage import upsert_watermark
from apps.copilot.modules.executing.universe import load_executing_collect_symbols
from apps.copilot.services.redis_wait import wait_for_sync_redis

logger = logging.getLogger(__name__)


async def run_job(
    session: AsyncSession,
    job_id: str,
    *,
    symbol: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    spec = next((j for j in JOB_REGISTRY if j.job_id == job_id), None)
    if spec is None:
        return {"job_id": job_id, "status": "error", "error": "unknown job_id"}

    redis = wait_for_sync_redis()
    symbols = [symbol.zfill(6)[-6:]] if symbol else await load_executing_collect_symbols(session)
    if not symbols and job_id not in ("bootstrap-sync",):
        return {"job_id": job_id, "status": "skip", "reason": "executing_collect_empty"}

    if job_id == "bootstrap-sync":
        results = []
        for sym in symbols or ["601138"]:
            r = await run_t0_collect(session, sym)
            results.append(r)
            await run_daily_pipeline(session, sym, redis_client=redis)
        await upsert_watermark(session, "bootstrap-sync", "*", success=True, trade_date=date.today())
        return {"job_id": job_id, "status": "ok", "symbols": results}

    if job_id == "quote-intraday":
        for sym in symbols:
            await quote_intraday_job(session, sym, redis)
        await upsert_watermark(session, job_id, "*", success=True, trade_date=date.today())
        return {"job_id": job_id, "status": "ok", "symbols": symbols}

    if job_id in ("l4-micro-eod", "l3-news-daily", "collect-once"):
        out = []
        for sym in symbols:
            out.append(await run_t0_collect(session, sym))
        await upsert_watermark(session, job_id, "*", success=True, trade_date=date.today())
        return {"job_id": job_id, "status": "ok", "results": out}

    if job_id == "daily-pipeline":
        out = []
        for sym in symbols:
            out.append(await run_daily_pipeline(session, sym, redis_client=redis))
        return {"job_id": job_id, "status": "ok", "results": out}

    return {"job_id": job_id, "status": "error", "error": "not implemented"}
