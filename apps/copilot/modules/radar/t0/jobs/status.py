"""radar-pipeline-status：水位 + 表内标的 stale。

[Ref: 27_ §2.8.3 · §5.2]
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.radar.t0.jobs.registry import JOB_REGISTRY, JobScope, cron_jobs
from apps.copilot.modules.radar.t0.jobs.runner import is_watermark_stale, stale_hours_for
from apps.copilot.modules.radar.t0.jobs.watermarks import list_watermarks, watermark_to_dict
from apps.copilot.modules.radar.t0.symbol_list import list_collect_symbol_rows, row_to_dict


async def build_pipeline_status(session: AsyncSession) -> dict[str, Any]:
    """仅报告 **collect 表内** 标的 + 各 job watermark stale。"""
    rows = await list_collect_symbol_rows(session, enabled_only=True)
    symbols = [row_to_dict(r) for r in rows]
    wm_rows = {w.job_id: w for w in await list_watermarks(session)}

    jobs: list[dict[str, Any]] = []
    for spec in cron_jobs():
        wm = wm_rows.get(spec.job_id)
        stale = is_watermark_stale(spec, last_success_at=wm.last_success_at if wm else None)
        jobs.append(
            {
                **watermark_to_dict(wm),
                "job_id": spec.job_id,
                "cadence": spec.cadence.value,
                "implemented": spec.implemented,
                "stale": stale,
                "stale_after_hours": stale_hours_for(spec.cadence),
            }
        )

    symbol_stale: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for s in symbols:
        last_at = s.get("last_collect_at")
        age_h = None
        if last_at:
            try:
                dt = datetime.fromisoformat(str(last_at))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_h = round((now - dt.astimezone(timezone.utc)).total_seconds() / 3600.0, 1)
            except ValueError:
                pass
        symbol_stale.append(
            {
                "symbol": s["symbol"],
                "name": s.get("name"),
                "last_collect_at": last_at,
                "last_collect_job": s.get("last_collect_job"),
                "age_hours": age_h,
                "stale": age_h is None or age_h > 36.0,
            }
        )

    return {
        "collect_symbol_count": len(symbols),
        "collect_symbols": symbols,
        "symbol_freshness": symbol_stale,
        "jobs": jobs,
        "collect_list_empty": len(symbols) == 0,
    }
