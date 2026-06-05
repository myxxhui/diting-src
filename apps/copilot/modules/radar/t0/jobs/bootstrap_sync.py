"""冷启动 bootstrap：对 stale / catch_up 的 job 补跑。

[Ref: 27_ §2.8.3]
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.radar.t0.jobs.registry import JOB_REGISTRY, JobCadence, JobScope, cron_jobs
from apps.copilot.modules.radar.t0.jobs.runner import is_watermark_stale, run_job
from apps.copilot.modules.radar.t0.jobs.watermarks import get_watermark, upsert_watermark
from apps.copilot.modules.radar.t0.symbol_list import load_generic_t0_collect_symbols

logger = logging.getLogger(__name__)


async def run_bootstrap_sync(
    session: AsyncSession,
    *,
    redis_client: Any = None,
    force: bool = False,
) -> dict[str, Any]:
    symbols = await load_generic_t0_collect_symbols(session, enabled_only=True)
    results: list[dict[str, Any]] = []

    targets = [s for s in cron_jobs()]
    if force:
        targets = list(JOB_REGISTRY)
        targets = [t for t in targets if t.job_id not in ("collect-once",)]

    for spec in targets:
        if spec.scope == JobScope.COLLECT and not symbols:
            logger.info("bootstrap skip %s: collect_list_empty", spec.job_id)
            results.append({"job_id": spec.job_id, "status": "skip", "reason": "collect_list_empty"})
            continue

        wm = await get_watermark(session, spec.job_id)
        stale = force or (wm is None) or is_watermark_stale(
            spec, last_success_at=wm.last_success_at if wm else None
        )
        if wm and wm.catch_up_pending:
            stale = True

        if not stale:
            results.append({"job_id": spec.job_id, "status": "fresh"})
            continue

        logger.info("bootstrap run job_id=%s force=%s", spec.job_id, force)
        try:
            out = await run_job(session, spec.job_id, redis_client=redis_client, force=force)
            results.append(out)
        except Exception as exc:  # noqa: BLE001
            logger.exception("bootstrap job %s failed", spec.job_id)
            await upsert_watermark(session, spec.job_id, success=False, error=str(exc)[:200])
            results.append({"job_id": spec.job_id, "status": "error", "error": str(exc)[:200]})

    await upsert_watermark(
        session,
        "bootstrap-sync",
        success=True,
        row_count=sum(1 for r in results if r.get("status") == "ok"),
    )
    return {"status": "ok", "jobs": len(results), "results": results}
