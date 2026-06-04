"""T0 CronJob / bootstrap 执行器。

[Ref: 27_ §2.8]
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.radar.t0.jobs.cache_merge import (
    merge_domain_patch,
    merge_macro_sector,
    merge_micro_into_cache,
    write_global_macro_cache,
)
from apps.copilot.modules.radar.t0.jobs.registry import JobCadence, JobScope, JobSpec, get_job_spec
from apps.copilot.modules.radar.t0.jobs.watermarks import upsert_watermark
from apps.copilot.modules.radar.t0.symbol_list import load_t0_collect_symbols, touch_collect_symbol
from apps.copilot.modules.radar.t0.jobs.collect_once import collect_once

logger = logging.getLogger(__name__)

_MICRO_FN = {
    "bars_250d": "collect_bars_250d",
    "northbound": "collect_northbound",
    "margin": "collect_margin",
    "dragon_tiger": "collect_dragon_tiger",
}


def _today_cn() -> date:
    return datetime.now(timezone(timedelta(hours=8))).date()


def stale_hours_for(cadence: JobCadence) -> float:
    if cadence == JobCadence.INTRADAY:
        return 1.0
    if cadence == JobCadence.DAILY:
        return 36.0
    if cadence == JobCadence.WEEKLY:
        return 8 * 24.0
    if cadence == JobCadence.MONTHLY:
        return 35 * 24.0
    if cadence in (JobCadence.QUARTERLY, JobCadence.ANNUAL):
        return 100 * 24.0
    return 36.0


def is_watermark_stale(
    spec: JobSpec,
    *,
    last_success_at: datetime | None,
) -> bool:
    if last_success_at is None:
        return True
    now = datetime.now(timezone.utc)
    ts = last_success_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_h = (now - ts.astimezone(timezone.utc)).total_seconds() / 3600.0
    return age_h > stale_hours_for(spec.cadence)


async def run_job(
    session: AsyncSession,
    job_id: str,
    *,
    redis_client: Any = None,
    force: bool = False,
) -> dict[str, Any]:
    """执行单个 job_id；返回摘要 JSON（供 CronJob 日志）。"""
    _ = force
    spec = get_job_spec(job_id)

    if job_id == "bootstrap-sync":
        from apps.copilot.modules.radar.t0.jobs.bootstrap_sync import run_bootstrap_sync

        return await run_bootstrap_sync(session, redis_client=redis_client, force=force)

    if job_id == "collect-once":
        rows = await collect_once(session, job_id=job_id, redis_client=redis_client)
        ok = sum(1 for r in rows if r.get("status") != "error" and "error" not in r)
        await upsert_watermark(
            session,
            job_id,
            success=True,
            row_count=len(rows),
            trade_date=_today_cn(),
        )
        return {"job_id": job_id, "status": "ok", "symbols": len(rows), "ok": ok}

    symbols: list[str] = []
    if spec.scope == JobScope.COLLECT:
        symbols = await load_t0_collect_symbols(session, enabled_only=True)
        if not symbols:
            await upsert_watermark(
                session,
                job_id,
                success=True,
                row_count=0,
                trade_date=_today_cn(),
                error=None,
            )
            logger.warning("job %s: collect_list_empty → no-op", job_id)
            return {"job_id": job_id, "status": "skip", "reason": "collect_list_empty"}

    if spec.scope == JobScope.GLOBAL:
        return await _run_global_job(session, spec, redis_client=redis_client)

    if spec.micro_key:
        return await _run_micro_job(session, spec, symbols)

    if spec.implemented:
        return await _run_domain_job(session, spec, symbols)

    await upsert_watermark(
        session,
        job_id,
        success=True,
        row_count=0,
        trade_date=_today_cn(),
        error="SKIP_REASON: collector 未注册",
    )
    return {"job_id": job_id, "status": "skip", "reason": "collector 未注册"}


async def _run_global_job(
    session: AsyncSession,
    spec: JobSpec,
    *,
    redis_client: Any = None,
) -> dict[str, Any]:
    from apps.copilot.modules.radar.t0.collectors.market_sentiment import (
        collect_market_sentiment_snapshot,
        upsert_sentiment_pg,
        write_sentiment_redis,
    )

    finalized = spec.job_id == "sentiment-eod"
    payload = await asyncio.to_thread(collect_market_sentiment_snapshot, finalized=finalized)
    if payload.get("status") == "ok":
        write_sentiment_redis(redis_client, payload)
        write_global_macro_cache(payload)
        if finalized:
            await upsert_sentiment_pg(session, payload)

    ok = payload.get("status") == "ok"
    await upsert_watermark(
        session,
        spec.job_id,
        success=ok,
        row_count=1 if ok else 0,
        trade_date=_today_cn(),
        error=None if ok else payload.get("detail"),
    )
    return {
        "job_id": spec.job_id,
        "status": "ok" if ok else "error",
        "advance_ratio": payload.get("advance_ratio"),
        "detail": payload.get("detail"),
    }


def _collect_for_domain_job(job_id: str, sym: str) -> tuple[str, dict[str, Any] | None]:
    """返回 (merge_mode, payload)；merge_mode: macro_sector | domain_patch | risk_bundle。"""
    from apps.copilot.modules.radar.t0.collectors import consensus, ecosystem, risk, sector

    if job_id == "macro-sector-daily":
        return "macro_sector", sector.collect_sector_context(sym)
    if job_id == "ecosystem-peer-daily":
        prof = ecosystem.collect_profile_extended(sym)
        industry = prof.get("industry") if prof.get("status") == "ok" else None
        return "domain_patch", {"domain": "ecosystem", "patch": {"peer_ranking": ecosystem.collect_peer_rank(sym, industry=industry)}}
    if job_id == "ecosystem-profile-monthly":
        return "domain_patch", {"domain": "ecosystem", "patch": {"profile": ecosystem.collect_profile_extended(sym)}}
    if job_id == "ecosystem-segments-quarterly":
        return "domain_patch", {"domain": "ecosystem", "patch": {"segment_breakdown": ecosystem.collect_segment_breakdown(sym)}}
    if job_id == "ecosystem-supply-chain-annual":
        return "domain_patch", {"domain": "ecosystem", "patch": {"supply_chain": ecosystem.collect_supply_chain(sym)}}
    if job_id == "consensus-weekly":
        return "domain_patch", {"domain": "consensus", "patch": consensus.collect_consensus(sym)}
    if job_id == "risk-financials-quarterly":
        bundle = risk.collect_risk_bundle(sym)
        return "domain_patch", {"domain": "risk", "patch": {"financial_slice": bundle.get("financial_slice")}}
    if job_id == "risk-pledge-unlock-weekly":
        bundle = risk.collect_risk_bundle(sym)
        return "domain_patch", {
            "domain": "risk",
            "patch": {
                "pledge": bundle.get("pledge"),
                "unlock_schedule": bundle.get("unlock_schedule"),
            },
        }
    if job_id == "risk-regulatory-daily":
        from apps.copilot.modules.radar.t0.collectors.risk import _collect_regulatory

        return "domain_patch", {"domain": "risk", "patch": {"regulatory_events": _collect_regulatory(sym)}}
    return "skip", None


async def _run_domain_job(
    session: AsyncSession,
    spec: JobSpec,
    symbols: list[str],
) -> dict[str, Any]:
    ok = skip = err = 0
    for sym in symbols:
        try:
            mode, payload = await asyncio.to_thread(_collect_for_domain_job, spec.job_id, sym)
            if mode == "skip" or payload is None:
                skip += 1
                continue
            if mode == "macro_sector":
                merge_macro_sector(sym, payload)
                st = "ok" if any(
                    (payload.get(k) or {}).get("status") == "ok"
                    for k in ("sector_momentum", "sector_flow")
                ) else "skip"
            else:
                domain = payload["domain"]
                patch = payload["patch"]
                merge_domain_patch(sym, domain, patch, source=f"cron:{spec.job_id}")
                st = "ok" if any(v.get("status") == "ok" for v in patch.values()) else "skip"

            if st == "ok":
                ok += 1
            else:
                skip += 1
            await touch_collect_symbol(session, sym, job_id=spec.job_id, trade_date=_today_cn())
        except Exception:  # noqa: BLE001
            err += 1
            logger.exception("domain job %s symbol=%s failed", spec.job_id, sym)

    await upsert_watermark(
        session,
        spec.job_id,
        success=err == 0 or ok > 0,
        row_count=ok,
        trade_date=_today_cn(),
        error=None if err == 0 else f"{err} 个标的采集失败",
    )
    return {
        "job_id": spec.job_id,
        "status": "ok" if ok > 0 else ("skip" if skip and not err else "error"),
        "symbols": len(symbols),
        "ok": ok,
        "skip": skip,
        "error": err,
    }


async def _run_micro_job(
    session: AsyncSession,
    spec: JobSpec,
    symbols: list[str],
) -> dict[str, Any]:
    fn_name = _MICRO_FN.get(spec.micro_key or "")
    if not fn_name:
        raise ValueError(f"无 collector 映射: {spec.micro_key}")

    from apps.copilot.modules.radar.t0.collectors import microstructure as micro_mod

    fn = getattr(micro_mod, fn_name)

    ok = skip = err = 0
    for sym in symbols:
        try:
            payload = await asyncio.to_thread(fn, sym)
            merge_micro_into_cache(sym, spec.micro_key or "", payload)
            st = payload.get("status")
            if st == "ok":
                ok += 1
            elif st == "skip":
                skip += 1
            else:
                err += 1
            await touch_collect_symbol(session, sym, job_id=spec.job_id, trade_date=_today_cn())
        except Exception:  # noqa: BLE001
            err += 1
            logger.exception("micro job %s symbol=%s failed", spec.job_id, sym)

    await upsert_watermark(
        session,
        spec.job_id,
        success=err == 0 or ok > 0,
        row_count=ok,
        trade_date=_today_cn(),
        error=None if err == 0 else f"{err} 个标的采集失败",
    )
    return {
        "job_id": spec.job_id,
        "status": "ok" if ok > 0 else ("skip" if skip and not err else "error"),
        "symbols": len(symbols),
        "ok": ok,
        "skip": skip,
        "error": err,
    }
