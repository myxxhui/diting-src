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
from apps.copilot.modules.radar.t0.symbol_list import (
    list_collect_symbol_rows,
    load_generic_t0_collect_symbols,
    row_to_dict,
    sync_executing_collect_mirror,
)


async def build_pipeline_status(session: AsyncSession) -> dict[str, Any]:
    """报告 **通用 T0 采集宇宙**（executing ∪ radar）+ 各 job watermark stale。"""
    await sync_executing_collect_mirror(session)
    generic = await load_generic_t0_collect_symbols(session, enabled_only=True)
    radar_by_sym = {
        r.symbol: r for r in await list_collect_symbol_rows(session, enabled_only=True)
    }
    symbols: list[dict[str, Any]] = []
    for sym in generic:
        row = radar_by_sym.get(sym)
        if row is not None:
            d = row_to_dict(row)
            d["source"] = (
                "executing_mirror" if row.enrolled_by == "executing_mirror" else "radar_table"
            )
        else:
            d = {
                "symbol": sym,
                "name": sym,
                "enabled": True,
                "enrolled_by": "executing_only",
                "source": "executing_only",
            }
        symbols.append(d)
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
        "generic_collect_symbols": generic,
        "symbol_freshness": symbol_stale,
        "jobs": jobs,
        "collect_list_empty": len(symbols) == 0,
        "sot": "load_generic_t0_collect_symbols",
    }
