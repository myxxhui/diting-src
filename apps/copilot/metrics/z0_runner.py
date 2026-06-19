"""Z0 段 A/C 采集 Job 执行器。

[Ref: 34_ §3.0b · 29_ §2]
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.metrics.collectors.m1_macro import collect_m1_bundle
from apps.copilot.metrics.collectors.m2_sector_heat import collect_m2_bundle
from apps.copilot.metrics.collectors.m3_capex import collect_capex_total
from apps.copilot.metrics.collectors.m5_liquidity import collect_m5_bundle
from apps.copilot.metrics.collectors.m6_jl import aggregate_jl_panel
from apps.copilot.metrics.synthesizer.ecosystem_scorer import score_ecosystem_bundle
from apps.copilot.metrics.synthesizer.wind_scan import synthesize_wind_scan
from apps.copilot.metrics.z0_registry import Z0_JOB_REGISTRY
from apps.copilot.metrics.z0_storage import (
    read_metric_redis,
    read_metrics_bundle,
    set_collect_progress,
    upsert_metric_pg,
    write_metric_redis,
    write_watermark_redis,
)
from apps.copilot.modules.strategic.z0_workflow import persist_wind_scan_from_synthesis

logger = logging.getLogger(__name__)


async def _persist_m1(session: AsyncSession, redis_client: Any, bundle: dict[str, Any]) -> None:
    parts = bundle.get("parts") or {}
    for key, snap in parts.items():
        if snap.get("status") != "ok" or not snap.get("metric_id"):
            continue
        mid = snap["metric_id"]
        write_metric_redis(redis_client, mid, snap)
        await upsert_metric_pg(session, mid, snap)


async def _persist_m5(session: AsyncSession, redis_client: Any, bundle: dict[str, Any]) -> None:
    parts = bundle.get("parts") or {}
    for snap in parts.values():
        if snap.get("status") != "ok" or not snap.get("metric_id"):
            continue
        write_metric_redis(redis_client, snap["metric_id"], snap)
        await upsert_metric_pg(session, snap["metric_id"], snap)


async def _persist_m2(session: AsyncSession, redis_client: Any, bundle: dict[str, Any]) -> None:
    parts = bundle.get("parts") or {}
    heat = parts.get("concept_heat") or {}
    if heat.get("status") == "ok":
        write_metric_redis(redis_client, "M.sector.concept_heat", heat)
        await upsert_metric_pg(session, "M.sector.concept_heat", heat)
    policy = parts.get("policy_direction") or {}
    if policy.get("status") == "ok":
        write_metric_redis(redis_client, "M.sector.policy_direction", policy)
        await upsert_metric_pg(session, "M.sector.policy_direction", policy)


async def run_z0_m1(session: AsyncSession, redis_client: Any) -> dict[str, Any]:
    bundle = collect_m1_bundle()
    await _persist_m1(session, redis_client, bundle)
    write_watermark_redis(
        redis_client,
        "z0-m1-macro",
        {"status": bundle.get("status"), "at": datetime.now(timezone.utc).isoformat()},
    )
    return {"job_id": "z0-m1-macro", **bundle}


async def run_z0_m5(session: AsyncSession, redis_client: Any) -> dict[str, Any]:
    pmi = read_metric_redis(redis_client, "M.macro.pmi")
    bundle = collect_m5_bundle(pmi)
    await _persist_m5(session, redis_client, bundle)
    write_watermark_redis(
        redis_client,
        "z0-m5-liquidity",
        {"status": bundle.get("status"), "at": datetime.now(timezone.utc).isoformat()},
    )
    return {"job_id": "z0-m5-liquidity", **bundle}


async def run_z0_policy_ingest(session: AsyncSession, redis_client: Any) -> dict[str, Any]:
    from apps.copilot.services.deepsea.policy_ingest import ingest_policy_feeds
    from apps.copilot.services.deepsea.policy_t1_dispatcher import dispatch_policy_t1

    result = ingest_policy_feeds()
    t1 = dispatch_policy_t1()
    write_watermark_redis(
        redis_client,
        "z0-policy-ingest",
        {
            "status": result.get("status"),
            "new_count": result.get("new_count"),
            "t1_processed": t1.get("processed"),
            "at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {"job_id": "z0-policy-ingest", **result, "t1_dispatch": t1}


async def run_z0_m2(session: AsyncSession, redis_client: Any, *, skip_policy_ingest: bool = False) -> dict[str, Any]:
    bundle = collect_m2_bundle(run_policy_ingest=not skip_policy_ingest)
    await _persist_m2(session, redis_client, bundle)
    write_watermark_redis(
        redis_client,
        "z0-m2-sector-heat",
        {"status": bundle.get("status"), "at": datetime.now(timezone.utc).isoformat()},
    )
    return {"job_id": "z0-m2-sector-heat", **bundle}


async def run_z0_m0(session: AsyncSession, redis_client: Any) -> dict[str, Any]:
    metrics = await read_metrics_bundle(session, redis_client)
    synth = synthesize_wind_scan(metrics)
    row = await persist_wind_scan_from_synthesis(session, synth)
    write_watermark_redis(
        redis_client,
        "z0-m0-wind-scan",
        {
            "status": synth.get("status"),
            "wind_scan_id": row.get("id"),
            "at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {"job_id": "z0-m0-wind-scan", "synthesis": synth, "wind_scan": row}


# ─── 段C 新增 ─── [Ref: 34_ §3.7 段C]

async def run_z0_m3(session: AsyncSession, redis_client: Any) -> dict[str, Any]:
    """Z0-M3 · 四云 Capex 采集（S1）."""
    result = collect_capex_total()
    mid = "M.policy.capex_total"
    write_metric_redis(redis_client, mid, result)
    await upsert_metric_pg(session, mid, result)
    write_watermark_redis(
        redis_client,
        "z0-m3-capex",
        {"status": result.get("status"), "at": datetime.now(timezone.utc).isoformat()},
    )
    return {"job_id": "z0-m3-capex", **result}


async def run_z0_m4(
    session: AsyncSession,
    redis_client: Any,
    *,
    niche_themes: set[str] | None = None,
    s_curve_position: str = "early",
) -> dict[str, Any]:
    """Z0-M4 · E1~E5 生态位评分（S2 · phase×niche）."""
    capex = read_metric_redis(redis_client, "M.policy.capex_total")
    if capex is None:
        bundle = await read_metrics_bundle(session, redis_client)
        capex = bundle.get("M.policy.capex_total") or {}
    policy = read_metric_redis(redis_client, "M.sector.policy_direction") or {}

    result = score_ecosystem_bundle(
        capex_metric=capex,
        policy_metric=policy,
        niche_themes=niche_themes,
        s_curve_position=s_curve_position,
    )
    mid = "M.niche.ecosystem_scores"
    write_metric_redis(redis_client, mid, result)
    await upsert_metric_pg(session, mid, result)
    write_watermark_redis(
        redis_client,
        "z0-m4-ecosystem",
        {"status": result.get("status"), "at": datetime.now(timezone.utc).isoformat()},
    )
    return {"job_id": "z0-m4-ecosystem", **result}


async def run_z0_m6(session: AsyncSession, redis_client: Any, *, board_id: int | None = None) -> dict[str, Any]:
    """Z0-M6 · JL1/JL2 红灯面板."""
    bundle = await read_metrics_bundle(session, redis_client)
    result = aggregate_jl_panel(metrics=bundle, board_id=board_id)
    mid = "M.strategic.jl_panel"
    write_metric_redis(redis_client, mid, result)
    await upsert_metric_pg(session, mid, result)
    panel = result.get("panel") or {}
    write_watermark_redis(
        redis_client,
        "z0-m6-jl",
        {"status": result.get("status"), "overall": panel.get("overall"), "at": datetime.now(timezone.utc).isoformat()},
    )
    return {"job_id": "z0-m6-jl", **result}


async def run_z0_segment_c(
    session: AsyncSession,
    redis_client: Any,
    *,
    board_id: int | None = None,
    niche_themes: set[str] | None = None,
    s_curve_position: str = "early",
) -> dict[str, Any]:
    """段C 全流程 M3 → M4 → M6.

    [Ref: 34_ §3.7 段C]
    """
    steps: dict[str, Any] = {}

    steps["m3"] = await run_z0_m3(session, redis_client)
    steps["m4"] = await run_z0_m4(
        session, redis_client,
        niche_themes=niche_themes, s_curve_position=s_curve_position,
    )
    steps["m6"] = await run_z0_m6(session, redis_client, board_id=board_id)

    status = "ok" if all(s.get("status") in ("ok", "partial") for s in steps.values()) else "partial"
    return {
        "job_id": "z0-segment-c-full",
        "status": status,
        "board_id": board_id,
        "steps": steps,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


# ─── 主入口 ──────────────────────────────────────────────────────────

async def run_z0_bootstrap(
    session: AsyncSession,
    redis_client: Any,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    rid = run_id or uuid.uuid4().hex[:12]

    def _progress(step: str, pct: int, detail: str = "") -> None:
        set_collect_progress(
            redis_client,
            rid,
            {"step": step, "pct": pct, "detail": detail, "run_id": rid},
        )

    _progress("z0-m1-macro", 10, "宏观 M1 全量（PMI/GDP/社融/M2/US10Y/VIX）")
    m1 = await run_z0_m1(session, redis_client)
    _progress("z0-m5-liquidity", 40, "北向+流动性 regime")
    m5 = await run_z0_m5(session, redis_client)
    _progress("z0-policy-ingest", 55, "政策 T0 ingest + T1 enum → DeepSea")
    pingest = await run_z0_policy_ingest(session, redis_client)
    _progress("z0-m2-sector-heat", 65, "概念板块+政策赛道")
    m2 = await run_z0_m2(session, redis_client, skip_policy_ingest=True)
    _progress("z0-m0-wind-scan", 85, "合成 wind_scan")
    m0 = await run_z0_m0(session, redis_client)
    _progress("done", 100, m0.get("synthesis", {}).get("status", ""))
    write_watermark_redis(
        redis_client,
        "z0-bootstrap-all",
        {"status": "ok", "run_id": rid, "at": datetime.now(timezone.utc).isoformat()},
    )
    return {
        "job_id": "z0-bootstrap-all",
        "status": "ok",
        "run_id": rid,
        "steps": {"m1": m1, "m5": m5, "policy_ingest": pingest, "m2": m2, "m0": m0},
    }


async def run_z0_job(
    session: AsyncSession,
    job_id: str,
    redis_client: Any,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    spec = next((j for j in Z0_JOB_REGISTRY if j.job_id == job_id), None)
    if spec is None:
        return {"job_id": job_id, "status": "error", "error": "unknown job_id"}

    if job_id == "z0-bootstrap-all":
        return await run_z0_bootstrap(session, redis_client, run_id=run_id)
    if job_id == "z0-m1-macro":
        return await run_z0_m1(session, redis_client)
    if job_id == "z0-m5-liquidity":
        return await run_z0_m5(session, redis_client)
    if job_id == "z0-policy-ingest":
        return await run_z0_policy_ingest(session, redis_client)
    if job_id == "z0-m2-sector-heat":
        return await run_z0_m2(session, redis_client)
    if job_id == "z0-m0-wind-scan":
        return await run_z0_m0(session, redis_client)
    if job_id == "z0-m3-capex":
        return await run_z0_m3(session, redis_client)
    if job_id == "z0-m4-ecosystem":
        return await run_z0_m4(session, redis_client)
    if job_id == "z0-m6-jl":
        return await run_z0_m6(session, redis_client)
    if job_id == "z0-segment-c-full":
        return await run_z0_segment_c(session, redis_client)
    return {"job_id": job_id, "status": "error", "error": "not implemented"}

