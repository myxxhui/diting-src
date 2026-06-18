"""Z0 采集管线状态（Make status / UI）。

[Ref: 34_ §3.0b · 29_ §4.2]
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.metrics.registry import load_metric_registry
from apps.copilot.metrics.z0_registry import Z0_JOB_REGISTRY
from apps.copilot.metrics.z0_storage import read_metric_redis, read_watermark_redis


async def build_z0_pipeline_status(
    session: AsyncSession,
    redis_client: Any,
) -> dict[str, Any]:
    from apps.copilot.metrics.z0_storage import read_metrics_bundle

    metrics = await read_metrics_bundle(session, redis_client)
    jobs = []
    for spec in Z0_JOB_REGISTRY:
        wm = read_watermark_redis(redis_client, spec.job_id)
        jobs.append(
            {
                "job_id": spec.job_id,
                "cron": spec.cron,
                "description": spec.description,
                "last_run": wm,
            }
        )
    ready = {
        "m1": metrics.get("M.macro.pmi", {}).get("status") == "ok",
        "m5": metrics.get("M.liq.regime_composite", {}).get("status") == "ok",
        "m2": metrics.get("M.sector.concept_heat", {}).get("status") == "ok",
    }
    return {
        "registry": load_metric_registry().get("schema_version"),
        "metrics_ready": ready,
        "segment_a_ready": ready["m1"] and ready["m5"],
        "wind_scan_ready": ready["m1"] and ready["m5"] and ready["m2"],
        "jobs": jobs,
        "metrics_sample": {
            k: {
                "status": v.get("status"),
                "as_of": v.get("as_of"),
                "series_count": v.get("series_count"),
            }
            for k, v in metrics.items()
        },
    }
