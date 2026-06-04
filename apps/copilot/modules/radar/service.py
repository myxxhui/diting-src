"""雷达扫描服务：建扫/查候选/promote。

[Ref: step_14 · M8]
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.common.holdings_sot import load_holdings_sot
from apps.copilot.db.models import (
    CampaignSymbol,
    ModelProfile,
    RadarCandidate,
    RadarScan,
    StageArtifact,
    WorkspaceArtifact,
)
from apps.copilot.modules.planning.falsify import ensure_default_falsify_tasks
from apps.copilot.modules.planning.funnel import (
    get_or_create_container,
    touch_last_analyzed,
    upsert_funnel_symbol,
)
from apps.copilot.modules.radar.persistence import recent_analysis_days, sync_bundle_to_db
from apps.copilot.modules.planning.monitor import ensure_three_pillars
from apps.copilot.modules.radar.model_router import DEFAULT_PROFILES
from apps.copilot.modules.radar.model_router import t1_step_label
from apps.copilot.modules.radar.t1_distill import build_t1_payload
from apps.copilot.modules.radar.pipeline import run_radar_pipeline
from apps.copilot.modules.radar.scanner import collect_t0_live, t1_to_candidate_fields
from apps.copilot.modules.radar.symbol_resolve import (
    RadarSymbolResolveError,
    _is_valid_chinese_name,
    display_name_for_symbol,
    resolve_radar_query,
)


def _should_persist_display_name(stored: str | None, sym: str, resolved: str) -> bool:
    return bool(
        resolved
        and resolved != sym
        and not _is_valid_chinese_name(stored, sym)
    )
from apps.copilot.modules.radar.t0_cache import (
    build_bundle_from_pipeline,
    load_cached,
    save_cache,
)

logger = logging.getLogger(__name__)


async def ensure_model_profiles(session: AsyncSession) -> None:
    for p in DEFAULT_PROFILES:
        existing = await session.scalar(
            select(ModelProfile).where(
                ModelProfile.workspace == p["workspace"],
                ModelProfile.task == p["task"],
            )
        )
        if existing:
            continue
        session.add(
            ModelProfile(
                workspace=p["workspace"],
                task=p["task"],
                tier=p["tier"],
                model_id=p["model_id"],
                override_allowed=p.get("override_allowed", True),
                pinned=p.get("pinned", False),
            )
        )
    await session.flush()


async def latest_scan_id_for_symbol(session: AsyncSession, symbol: str) -> int | None:
    """候选池点击加载：取该标的最近一次已完成扫描 id。"""
    sym = (symbol or "").zfill(6)[-6:]
    if not sym:
        return None
    cid = await session.scalar(
        select(RadarCandidate.scan_id)
        .where(RadarCandidate.symbol == sym, RadarCandidate.scan_id.isnot(None))
        .order_by(RadarCandidate.id.desc())
        .limit(1)
    )
    if cid:
        return int(cid)
    sid = await session.scalar(
        select(RadarScan.id)
        .where(RadarScan.query_text == sym, RadarScan.status == "done")
        .order_by(RadarScan.id.desc())
        .limit(1)
    )
    return int(sid) if sid else None


async def create_symbol_scan(
    session: AsyncSession,
    *,
    query_text: str,
    redis_client: Any = None,
    enable_t0: bool = True,
    enable_t1: bool = True,
    enable_t2: bool = False,
    t1_mode: str | None = None,
    t2_model: str | None = None,
    force_refresh: bool = False,
    progress_cb: Any = None,
    scan_id: int | None = None,
) -> dict[str, Any]:
    """模式 C：按勾选阶段执行 T0/T1/T2。"""
    try:
        sym, name = resolve_radar_query(query_text)
    except RadarSymbolResolveError as exc:
        raise ValueError(str(exc)) from exc

    if progress_cb is not None:
        progress_cb("resolve", f"已解析 {sym} · {name}", 8, "")

    if scan_id is not None:
        scan = await session.get(RadarScan, scan_id)
        if scan is None:
            raise ValueError(f"scan {scan_id} not found")
        candidate = await session.scalar(
            select(RadarCandidate).where(RadarCandidate.scan_id == scan_id).limit(1)
        )
        if candidate is None:
            candidate = RadarCandidate(scan_id=scan.id, symbol=sym, name=name)
            session.add(candidate)
            await session.flush()
    else:
        scan = RadarScan(
            input_type="symbol",
            query_text=sym,
            status="running",
        )
        session.add(scan)
        await session.flush()
        candidate = RadarCandidate(scan_id=scan.id, symbol=sym, name=name)
        session.add(candidate)
        await session.flush()

    pipe = await run_radar_pipeline(
        session,
        symbol=sym,
        name=name,
        scan_id=scan.id,
        candidate_id=candidate.id,
        redis_client=redis_client,
        enable_t0=enable_t0,
        enable_t1=enable_t1,
        enable_t2=enable_t2,
        t1_mode=t1_mode,
        t2_model=t2_model,
        force_refresh_t0=force_refresh and enable_t0,
        force_refresh_t2=force_refresh and enable_t2,
        progress_cb=progress_cb,
    )

    version_id: str | None = None
    if force_refresh or not pipe.get("t2_from_cache") or not pipe.get("t0_cache_hit"):
        bundle = build_bundle_from_pipeline(
            pipe,
            source="scan_force_refresh" if force_refresh else "scan_live",
        )
        # live Opus 失败时勿用 error T2 覆盖本机预拉并已 sync 的 ok 缓存（no-mock · 防污染）
        new_t2 = bundle.get("t2_verdict") or {}
        if enable_t2 and new_t2.get("status") != "ok" and not force_refresh:
            from apps.copilot.modules.radar.t2_resolve import resolve_ok_t2_verdict

            prior_t2 = await resolve_ok_t2_verdict(session, sym)
            if prior_t2:
                bundle["t2_verdict"] = prior_t2
                pipe["t2_verdict"] = prior_t2
                pipe["t2_from_cache"] = True
        version_id = save_cache(bundle)
        await sync_bundle_to_db(session, bundle)
    elif pipe.get("t0_cache_hit"):
        latest = load_cached(sym, require_fresh=False)
        if latest:
            version_id = str(latest.get("version_id") or "")

    t2 = pipe["t2_verdict"]
    fields = t1_to_candidate_fields(pipe["t0_raw"], pipe["t1_distilled"], t2)
    field_raw_json = fields.pop("raw_json", {})
    for k, v in fields.items():
        if hasattr(candidate, k):
            setattr(candidate, k, v)

    artifact_ids = [x for x in (pipe["t0_id"], pipe["t1_id"], pipe["t2_id"]) if x]
    snapshot = {
        "symbol": sym,
        "name": name,
        "workspace_artifact_id": pipe["wa_id"],
        "artifact_ids": artifact_ids,
    }
    candidate.raw_json = {**field_raw_json, "analysis_snapshot": snapshot}

    cost = field_raw_json.get("cost") or {}
    scan.status = "done"
    scan.summary_json = {
        "candidate_count": 1,
        "symbol": sym,
        "enable_t0": enable_t0,
        "enable_t1": enable_t1,
        "enable_t2": enable_t2,
        "t1_mode": t1_mode,
        "t2_model": t2_model,
        "t0_cache_hit": bool(pipe["t0_raw"].get("cache_hit")),
        "t2_from_cache": bool(pipe.get("t2_from_cache")),
        "force_refresh": force_refresh,
        "cache_version_id": version_id,
        "confidence": fields.get("confidence"),
        "t2_status": t2.get("status"),
        "t2_detail": t2.get("detail"),
        "cost": cost,
    }

    if progress_cb is not None:
        progress_cb("persist", "写入缓存与候选库", 92, "")

    await upsert_funnel_symbol(session, sym, name, stage="radar_intake")
    await touch_last_analyzed(session, sym)
    await session.flush()

    if progress_cb is not None:
        progress_cb("done", "分析完成", 100, "")

    return await get_scan(session, scan.id)


async def run_scan_job(
    scan_id: int,
    query_text: str,
    *,
    enable_t0: bool,
    enable_t1: bool,
    enable_t2: bool,
    t1_mode: str | None,
    t2_model: str | None,
    force_refresh: bool,
    redis_client: Any,
) -> None:
    """后台执行深度扫描（独立 DB 会话 · Redis 进度供 HTMX 轮询）。"""
    from apps.copilot.db.database import AsyncSessionLocal
    from apps.copilot.modules.radar.scan_progress import fail_scan, finish_scan, make_progress_callback

    cb = make_progress_callback(redis_client, scan_id)
    async with AsyncSessionLocal() as session:
        try:
            await create_symbol_scan(
                session,
                query_text=query_text,
                redis_client=redis_client,
                enable_t0=enable_t0,
                enable_t1=enable_t1,
                enable_t2=enable_t2,
                t1_mode=t1_mode,
                t2_model=t2_model,
                force_refresh=force_refresh,
                progress_cb=cb,
                scan_id=scan_id,
            )
            await session.commit()
            finish_scan(redis_client, scan_id, {"scan_id": scan_id})
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.exception("scan job %s failed", scan_id)
            try:
                async with AsyncSessionLocal() as session2:
                    scan = await session2.get(RadarScan, scan_id)
                    if scan:
                        scan.status = "error"
                        from apps.copilot.modules.radar.errors import friendly_scan_error

                        friendly = friendly_scan_error(exc)
                        scan.summary_json = {
                            "error": friendly,
                            "error_code": type(exc).__name__,
                        }
                        await session2.commit()
            except Exception:  # noqa: BLE001
                pass
            from apps.copilot.modules.radar.errors import friendly_scan_error

            friendly = friendly_scan_error(exc)
            fail_scan(redis_client, scan_id, friendly)


async def collect_symbol_t0_only(
    session: AsyncSession,
    *,
    query_text: str,
    redis_client: Any = None,
    run_t1: bool = True,
    progress_cb: Any = None,
) -> dict[str, Any]:
    """仅采集 T0（可选自动 T1），不写 T2；结果入库并返回状态。"""
    try:
        sym, name = resolve_radar_query(query_text)
    except RadarSymbolResolveError as exc:
        raise ValueError(str(exc)) from exc

    if progress_cb is not None:
        progress_cb("resolve", f"已解析 {sym} · {name}", 8, "")
        t0_raw = await collect_t0_live(sym, name=name, on_step=progress_cb)
        progress_cb("t1", t1_step_label(), 88, "构建上下文矩阵…")
        t1_payload = await build_t1_payload(t0_raw)
        pipe = {
            "t0_raw": t0_raw,
            "t1_distilled": t1_payload,
            "t2_verdict": {"status": "skipped", "detail": "仅采集模式"},
            "t0_id": None,
            "t1_id": None,
            "t2_id": None,
            "wa_id": None,
            "t2_from_cache": False,
        }
    else:
        pipe = await run_radar_pipeline(
            session,
            symbol=sym,
            name=name,
            enable_t0=True,
            enable_t1=run_t1,
            enable_t2=False,
            force_refresh_t0=True,
            force_refresh_t2=False,
            redis_client=redis_client,
        )

    if progress_cb:
        progress_cb("persist", "写入文件缓存与数据库", 96, "")

    bundle = build_bundle_from_pipeline(pipe, source="collect_t0")
    vid = save_cache(bundle)
    await sync_bundle_to_db(session, bundle)
    await upsert_funnel_symbol(session, sym, name, stage="radar_intake")
    await touch_last_analyzed(session, sym)
    await session.flush()

    ok_parts = sum(
        1
        for k in ("quote", "profile", "financials", "valuation")
        if (pipe["t0_raw"].get(k) or {}).get("status") == "ok"
    )
    return {
        "symbol": sym,
        "name": name,
        "version_id": vid,
        "t0_cache_hit": bool(pipe["t0_raw"].get("cache_hit")),
        "t1_done": run_t1,
        "t0_ok_parts": ok_parts,
        "status": "ok",
    }


async def run_collect_job(
    job_id: str,
    query_text: str,
    redis_client: Any,
) -> None:
    """后台执行采集（独立 DB 会话 · 更新 Redis 进度）。"""
    from apps.copilot.db.database import AsyncSessionLocal
    from apps.copilot.modules.radar.collect_progress import (
        fail_job,
        finish_job,
        init_job,
        make_progress_callback,
    )

    cb = make_progress_callback(redis_client, job_id)
    try:
        sym, name = resolve_radar_query(query_text)
    except RadarSymbolResolveError as exc:
        fail_job(redis_client, job_id, str(exc))
        return

    init_job(redis_client, job_id, symbol=sym, name=name)

    async with AsyncSessionLocal() as session:
        try:
            result = await collect_symbol_t0_only(
                session,
                query_text=query_text,
                redis_client=redis_client,
                progress_cb=cb,
            )
            await session.commit()
            finish_job(redis_client, job_id, result)
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            fail_job(redis_client, job_id, str(exc))
            logger.exception("collect job %s failed", job_id)


def _resolve_name(symbol: str) -> str:
    try:
        sot = load_holdings_sot()
        ent = sot.by_symbol(symbol.zfill(6)[-6:])
        if ent:
            return ent.name or symbol
    except Exception:  # noqa: BLE001
        pass
    return symbol


async def get_scan(
    session: AsyncSession,
    scan_id: int,
    *,
    hydrate_t2: bool = True,
) -> dict[str, Any]:
    scan = await session.scalar(
        select(RadarScan)
        .where(RadarScan.id == scan_id)
        .options(selectinload(RadarScan.candidates))
    )
    if scan is None:
        raise ValueError(f"scan {scan_id} not found")
    return await _scan_to_dict(scan, session=session if hydrate_t2 else None)


async def _scan_to_dict(
    scan: RadarScan,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for c in (scan.candidates or []):
        d = _candidate_to_dict(c)
        if session is not None:
            from apps.copilot.modules.radar.t2_resolve import hydrate_candidate_for_display

            d = await hydrate_candidate_for_display(session, d)
        candidates.append(d)
    return {
        "id": scan.id,
        "input_type": scan.input_type,
        "query_text": scan.query_text,
        "status": scan.status,
        "summary_json": scan.summary_json,
        "created_at": scan.created_at.isoformat() if scan.created_at else None,
        "candidates": candidates,
    }


def _candidate_to_dict(c: RadarCandidate) -> dict[str, Any]:
    raw = c.raw_json or {}
    return {
        "id": c.id,
        "scan_id": c.scan_id,
        "symbol": c.symbol,
        "name": c.name,
        "concept": c.concept,
        "industry": c.industry,
        "niche_text": c.niche_text,
        "value_chain_pos": c.value_chain_pos,
        "is_leader": c.is_leader,
        "leader_confidence": c.leader_confidence,
        "moat_level": c.moat_level,
        "profit_quality": c.profit_quality,
        "market_phase": c.market_phase,
        "catalyst_window": c.catalyst_window,
        "risk_summary": c.risk_summary,
        "confidence": c.confidence,
        "evidence_ref": c.evidence_ref,
        "deep_analysis": raw.get("deep_analysis") or {},
        "t2_status": raw.get("t2_status"),
        "t2_detail": raw.get("t2_detail"),
        "cost": raw.get("cost") or {},
    }


async def _ui_hidden_symbols(session: AsyncSession) -> set[str]:
    """前端已移除（ui_removed_at）的标的代码集合。"""
    from apps.copilot.db.models import CampaignSymbol

    rows = await session.scalars(
        select(CampaignSymbol.symbol).where(CampaignSymbol.ui_removed_at.isnot(None))
    )
    return {(s or "").zfill(6)[-6:] for s in rows if s}


async def list_recent_candidates(
    session: AsyncSession,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """扫描候选区：近 N 天分析过的标的 + 漏斗 radar_intake/planning/roadmap（去重）。"""
    from apps.copilot.modules.planning.funnel import list_funnel_symbols

    window = timedelta(days=recent_analysis_days())
    cutoff = datetime.now(timezone.utc) - window
    hidden = await _ui_hidden_symbols(session)

    funnel_rows = await list_funnel_symbols(
        session,
        stages=("radar_intake", "roadmap", "planning"),
    )
    funnel_by_sym: dict[str, CampaignSymbol] = {}
    for row in funnel_rows:
        sym = (row.symbol or "").zfill(6)[-6:]
        if not sym:
            continue
        analyzed = row.last_analyzed_at or row.updated_at
        if analyzed and analyzed.tzinfo is None:
            analyzed = analyzed.replace(tzinfo=timezone.utc)
        if analyzed and analyzed >= cutoff:
            funnel_by_sym[sym] = row

    rows = await session.scalars(
        select(RadarCandidate).order_by(RadarCandidate.id.desc()).limit(limit * 5)
    )
    cand_by_sym: dict[str, RadarCandidate] = {}
    for c in rows:
        sym = (c.symbol or "").zfill(6)[-6:]
        if sym and sym not in cand_by_sym:
            cand_by_sym[sym] = c

    all_syms = list(dict.fromkeys(list(funnel_by_sym.keys()) + list(cand_by_sym.keys())))
    # 批量用内存 code 表（轻量 API 预热）；缺的再单标的补拉（不拉全市场 spot）
    from apps.copilot.modules.radar.symbol_resolve import _code_name_map, _resolve_name_single

    code_map = _code_name_map()
    out: list[dict[str, Any]] = []
    for sym in all_syms:
        if sym in hidden:
            continue
        c = cand_by_sym.get(sym)
        fr = funnel_by_sym.get(sym)
        if c:
            d = _candidate_to_dict(c)
        else:
            d = {
                "id": None,
                "scan_id": None,
                "symbol": sym,
                "name": code_map.get(sym) or sym,
                "confidence": None,
                "market_phase": None,
            }
        stored = d.get("name")
        if _is_valid_chinese_name(stored, sym):
            resolved = (stored or "").strip()
        elif sym in code_map:
            resolved = code_map[sym]
        else:
            resolved = await asyncio.to_thread(_resolve_name_single, sym)
            if _is_valid_chinese_name(resolved, sym):
                code_map[sym] = resolved
        d["name"] = resolved
        if c is not None and _should_persist_display_name(c.name, sym, resolved):
            c.name = resolved
        if fr is not None and _should_persist_display_name(fr.name, sym, resolved):
            fr.name = resolved
        stage = fr.funnel_stage if fr else "radar_intake"
        d["funnel_stage"] = stage
        d["funnel_symbol_id"] = fr.id if fr else None
        d["already_promoted"] = stage in ("planning", "roadmap", "executing")
        d["in_scan_pool"] = stage in ("radar_intake", "roadmap", "planning")
        if not d.get("scan_id"):
            lid = await latest_scan_id_for_symbol(session, sym)
            if lid:
                d["scan_id"] = lid
        out.append(d)
        if len(out) >= limit:
            break
    return out


async def list_candidate_artifacts(
    session: AsyncSession,
    candidate_id: int,
) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(StageArtifact)
        .where(StageArtifact.candidate_id == candidate_id)
        .order_by(StageArtifact.id)
    )
    return [
        {
            "id": a.id,
            "stage": a.stage,
            "model_id": a.model_id,
            "input_refs": a.input_refs,
            "latency_ms": a.latency_ms,
            "token_cost": a.token_cost,
            "produced_at": a.produced_at.isoformat() if a.produced_at else None,
            "payload_keys": list((a.payload_json or {}).keys()),
        }
        for a in rows
    ]


async def promote_candidate(
    session: AsyncSession,
    candidate_id: int,
    *,
    new_theme: Optional[str] = None,  # 兼容旧签名，已忽略（不再按 theme 建 campaign）
    campaign_id: Optional[int] = None,  # 兼容旧签名，已忽略（统一挂唯一容器）
    target_stage: str = "planning",
    redis_client: Any = None,
) -> dict[str, Any]:
    """雷达候选晋级 = 把标的推进到漏斗 planning 区（**不新建 campaign**）。

    标的级漏斗：按 symbol 全局 find-or-create 唯一 funnel 记录并前向推进 stage，
    彻底杜绝"一标的多 campaign"重复。
    """
    candidate = await session.get(RadarCandidate, candidate_id)
    if candidate is None:
        raise ValueError("candidate not found")

    snapshot = (candidate.raw_json or {}).get("analysis_snapshot") or {
        "symbol": candidate.symbol,
        "name": candidate.name,
        "assessment": _candidate_to_dict(candidate),
    }

    container = await get_or_create_container(session)
    sym = candidate.symbol.zfill(6)[-6:]

    row = await upsert_funnel_symbol(
        session,
        sym,
        candidate.name or sym,
        stage=target_stage,
        analysis_snapshot=snapshot,
        promoted_from_candidate_id=candidate_id,
    )

    await ensure_three_pillars(session, container.id, sym)
    await ensure_default_falsify_tasks(session, container.id, sym)

    wa = await session.scalar(
        select(WorkspaceArtifact)
        .where(WorkspaceArtifact.candidate_id == candidate_id)
        .order_by(WorkspaceArtifact.id.desc())
        .limit(1)
    )
    if wa:
        wa.campaign_id = container.id

    await touch_last_analyzed(session, sym)
    await session.flush()
    return {
        "campaign_id": container.id,
        "candidate_id": candidate_id,
        "symbol": sym,
        "name": candidate.name or sym,
        "funnel_stage": row.funnel_stage,
        "analysis_snapshot": snapshot,
        "human_confirmation_required": True,
        "execute_mode": "advisory",
    }
