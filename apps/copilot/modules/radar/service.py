"""雷达扫描服务：建扫/查候选/promote。

[Ref: step_14 · M8]
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.common.holdings_sot import load_holdings_sot
from apps.copilot.db.models import (
    ModelProfile,
    RadarCandidate,
    RadarScan,
    StageArtifact,
    WorkspaceArtifact,
)
from apps.copilot.modules.planning.falsify import ensure_default_falsify_tasks
from apps.copilot.modules.planning.funnel import (
    get_or_create_container,
    upsert_funnel_symbol,
)
from apps.copilot.modules.planning.monitor import ensure_three_pillars
from apps.copilot.modules.radar.model_router import DEFAULT_PROFILES
from apps.copilot.modules.radar.pipeline import run_radar_pipeline
from apps.copilot.modules.radar.scanner import t1_to_candidate_fields


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


async def create_symbol_scan(
    session: AsyncSession,
    *,
    query_text: str,
    redis_client: Any = None,
    enable_t2: bool = True,
) -> dict[str, Any]:
    """模式 C：模糊标的深度分析（默认含 T2 Opus 9 维）。"""
    sym = query_text.strip().zfill(6)[-6:]
    name = _resolve_name(sym)

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
        enable_t2=enable_t2,
    )

    t2 = pipe["t2_verdict"]
    fields = t1_to_candidate_fields(pipe["t0_raw"], pipe["t1_distilled"], t2)
    field_raw_json = fields.pop("raw_json", {})
    for k, v in fields.items():
        if hasattr(candidate, k):
            setattr(candidate, k, v)

    snapshot = {
        "symbol": sym,
        "name": name,
        "workspace_artifact_id": pipe["wa_id"],
        "artifact_ids": [pipe["t0_id"], pipe["t1_id"], pipe["t2_id"]],
    }
    candidate.raw_json = {**field_raw_json, "analysis_snapshot": snapshot}

    cost = field_raw_json.get("cost") or {}
    scan.status = "done"
    scan.summary_json = {
        "candidate_count": 1,
        "symbol": sym,
        "enable_t2": enable_t2,
        "t0_cache_hit": bool(pipe["t0_raw"].get("cache_hit")),
        "confidence": fields.get("confidence"),
        "t2_status": t2.get("status"),
        "t2_detail": t2.get("detail"),
        "cost": cost,
    }

    await session.flush()
    return await get_scan(session, scan.id)


def _resolve_name(symbol: str) -> str:
    try:
        sot = load_holdings_sot()
        ent = sot.by_symbol(symbol.zfill(6)[-6:])
        if ent:
            return ent.name or symbol
    except Exception:  # noqa: BLE001
        pass
    return symbol


async def get_scan(session: AsyncSession, scan_id: int) -> dict[str, Any]:
    scan = await session.scalar(
        select(RadarScan)
        .where(RadarScan.id == scan_id)
        .options(selectinload(RadarScan.candidates))
    )
    if scan is None:
        raise ValueError(f"scan {scan_id} not found")
    return _scan_to_dict(scan)


def _scan_to_dict(scan: RadarScan) -> dict[str, Any]:
    return {
        "id": scan.id,
        "input_type": scan.input_type,
        "query_text": scan.query_text,
        "status": scan.status,
        "summary_json": scan.summary_json,
        "created_at": scan.created_at.isoformat() if scan.created_at else None,
        "candidates": [_candidate_to_dict(c) for c in (scan.candidates or [])],
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


async def list_recent_candidates(
    session: AsyncSession,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """雷达区 = 扫描工作台：最近扫描候选（按 symbol 去重保留最新）+ 是否已晋级。"""
    from apps.copilot.db.models import CampaignSymbol

    rows = await session.scalars(
        select(RadarCandidate).order_by(RadarCandidate.id.desc()).limit(limit * 3)
    )
    promoted = await session.scalars(select(CampaignSymbol.symbol))
    promoted_syms = {(s or "").zfill(6)[-6:] for s in promoted}

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for c in rows:
        sym = (c.symbol or "").zfill(6)[-6:]
        if not sym or sym in seen:
            continue
        seen.add(sym)
        d = _candidate_to_dict(c)
        d["already_promoted"] = sym in promoted_syms
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

    await session.flush()
    return {
        "campaign_id": container.id,
        "candidate_id": candidate_id,
        "symbol": sym,
        "funnel_stage": row.funnel_stage,
        "analysis_snapshot": snapshot,
        "human_confirmation_required": True,
        "execute_mode": "advisory",
    }
