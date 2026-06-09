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
    run_batch_daily_pipeline,
    run_daily_bars_incremental_sync,
    run_daily_bars_sync,
    run_daily_bars_sync_all,
    run_daily_pipeline,
    run_smart_money_backfill_check,
    run_smart_money_eod,
    run_level2_super_order_backfill_check,
    run_level2_super_order_eod,
    run_t0_collect,
    vol_div_15m_job,
)
from apps.copilot.modules.executing.storage import upsert_watermark
from apps.copilot.modules.executing.universe import load_executing_collect_symbols
from apps.copilot.services.redis_wait import wait_for_sync_redis

logger = logging.getLogger(__name__)


_JOB_ALIASES = {
    "quote-intraday-close": "quote-intraday",
    "l4-vol-div-15m-open": "l4-vol-div-15m",
    "l4-vol-div-15m-close": "l4-vol-div-15m",
}


async def run_job(
    session: AsyncSession,
    job_id: str,
    *,
    symbol: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    canonical = _JOB_ALIASES.get(job_id, job_id)
    spec = next((j for j in JOB_REGISTRY if j.job_id == job_id), None)
    if spec is None:
        return {"job_id": job_id, "status": "error", "error": "unknown job_id"}

    _REDIS_JOBS = frozenset(
        {
            "bootstrap-sync",
            "quote-intraday",
            "quote-intraday-close",
            "l4-vol-div-15m",
            "l4-vol-div-15m-open",
            "l4-vol-div-15m-close",
            "l4-atr-bars-sync",
            "l4-smart-money-backfill",
            "l4-smart-money-eod",
            "l2-super-order-backfill",
            "l2-super-order-eod",
            "l4-margin-skew-morning",
            "l4-turnover-accel-eod",
            "daily-pipeline",
        }
    )
    redis = wait_for_sync_redis() if job_id in _REDIS_JOBS else None
    symbols = [symbol.zfill(6)[-6:]] if symbol else await load_executing_collect_symbols(session)
    if not symbols and job_id not in ("bootstrap-sync",):
        return {"job_id": job_id, "status": "skip", "reason": "executing_collect_empty"}

    if job_id == "bootstrap-sync":
        syms = symbols or ["601138"]
        results = []
        for sym in syms:
            results.append(await run_t0_collect(session, sym))
        batch = await run_batch_daily_pipeline(session, syms, redis_client=redis)
        await upsert_watermark(session, "bootstrap-sync", "*", success=True, trade_date=date.today())
        return {"job_id": job_id, "status": "ok", "symbols": results, "batch": batch}

    if canonical == "quote-intraday":
        from apps.copilot.db.datetime_util import shanghai_now_iso

        started_at = shanghai_now_iso()
        logger.info(
            "[quote-intraday] 开始执行 · 北京时间=%s · 标的=%s",
            started_at,
            ",".join(symbols),
        )
        results = []
        for sym in symbols:
            results.append(await quote_intraday_job(session, sym, redis))
        ok = [r for r in results if r.get("status") == "ok"]
        finished_at = shanghai_now_iso()
        await upsert_watermark(
            session,
            job_id,
            "*",
            success=bool(ok),
            trade_date=date.today(),
            row_count=len(ok),
            error=None if ok else "no_intraday_draft",
        )
        logger.info(
            "[quote-intraday] 执行结束 · 北京时间=%s · 成功=%d/%d",
            finished_at,
            len(ok),
            len(results),
        )
        return {
            "job_id": job_id,
            "status": "ok" if ok else "skip",
            "started_at": started_at,
            "executed_at": finished_at,
            "results": results,
        }

    if canonical == "l4-vol-div-15m":
        from apps.copilot.db.datetime_util import shanghai_now_iso

        started_at = shanghai_now_iso()
        logger.info(
            "[l4-vol-div-15m] 开始 · 北京时间=%s · 标的=%s",
            started_at,
            ",".join(symbols),
        )
        results = []
        for sym in symbols:
            results.append(await vol_div_15m_job(session, sym, redis))
        ok = [r for r in results if r.get("status") == "ok"]
        finished_at = shanghai_now_iso()
        await upsert_watermark(
            session,
            "l4-vol-div-15m",
            "*",
            success=bool(ok),
            trade_date=date.today(),
            row_count=sum(r.get("bars_count", 0) for r in ok),
            error=None if ok else "no_15m_bars",
        )
        logger.info(
            "[l4-vol-div-15m] 结束 · 北京时间=%s · 成功=%d/%d",
            finished_at,
            len(ok),
            len(results),
        )
        return {
            "job_id": job_id,
            "status": "ok" if ok else "error",
            "started_at": started_at,
            "executed_at": finished_at,
            "results": results,
        }

    if job_id == "executing-bars250-bootstrap":
        result = await run_daily_bars_sync_all(session)
        return {"job_id": job_id, **result}

    if job_id == "l4-atr-bars-sync":
        out = []
        for sym in symbols:
            out.append(
                await run_daily_bars_incremental_sync(session, sym, redis_client=redis)
            )
        failed = [r for r in out if r.get("status") == "error"]
        await upsert_watermark(
            session,
            job_id,
            "*",
            success=not failed,
            trade_date=date.today(),
            row_count=sum(r.get("bars_count", 0) for r in out),
            error=failed[0].get("error") if failed else None,
        )
        return {
            "job_id": job_id,
            "status": "error" if failed else "ok",
            "results": out,
        }

    if job_id == "l4-smart-money-backfill":
        result = await run_smart_money_backfill_check(session, symbols, redis)
        return result

    if job_id == "l4-smart-money-eod":
        result = await run_smart_money_eod(session, symbols, redis)
        return result

    if job_id == "l2-super-order-backfill":
        result = await run_level2_super_order_backfill_check(session, symbols, redis)
        return result

    if job_id == "l2-super-order-eod":
        result = await run_level2_super_order_eod(session, symbols, redis)
        return result

    if job_id == "l4-margin-skew-morning":
        from apps.copilot.modules.executing.orchestrator import run_margin_skew_morning

        result = await run_margin_skew_morning(session, symbols, redis)
        return result

    if job_id == "l4-turnover-accel-eod":
        from apps.copilot.modules.executing.orchestrator import run_turnover_acceleration_eod

        result = await run_turnover_acceleration_eod(session, symbols, redis)
        return result

    if job_id in ("l4-micro-eod", "l3-news-daily", "collect-once"):
        out = []
        for sym in symbols:
            out.append(await run_t0_collect(session, sym))
        await upsert_watermark(session, job_id, "*", success=True, trade_date=date.today())
        return {"job_id": job_id, "status": "ok", "results": out}

    if job_id == "daily-pipeline":
        batch = await run_batch_daily_pipeline(session, symbols, redis_client=redis)
        return {"job_id": job_id, "status": batch.get("status", "ok"), "batch": batch}

    return {"job_id": job_id, "status": "error", "error": "not implemented"}
