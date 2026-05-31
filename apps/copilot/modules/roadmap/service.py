"""滚动路线图服务：时间线编排 · 合理性 · 归档滚动闭环。

[Ref: step_15 §7.1]
"""
from __future__ import annotations

import os
import re
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.copilot.db.models import (
    Campaign,
    CampaignSymbol,
    CampaignTimeline,
    RadarCandidate,
    RegimeAssessment,
)
from apps.copilot.modules.planning.funnel import set_stage
from apps.copilot.modules.planning.monitor import ensure_regime_patrol
from apps.copilot.modules.roadmap.feasibility import evaluate_timeline_feasibility
from apps.copilot.modules.roadmap.regime import assess_symbol_regime, regime_to_dict


def default_build_lead_days() -> int:
    return int(os.environ.get("ROADMAP_BUILD_LEAD_DAYS", "15"))


def _parse_catalyst_window(raw: Optional[str], anchor: Optional[date] = None) -> tuple[date, date, date]:
    """从 catalyst_window 字符串解析 anchor + window。"""
    today = date.today()
    anchor = anchor or today + timedelta(days=90)
    if not raw:
        return anchor, anchor - timedelta(days=30), anchor + timedelta(days=14)

    s = raw.strip()
    m = re.match(r"(\d{4})-Q(\d)", s, re.I)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        month = {1: 3, 2: 6, 3: 9, 4: 12}[q]
        anchor = date(y, month, 15)
    else:
        try:
            anchor = date.fromisoformat(s[:10])
        except ValueError:
            pass

    w_start = anchor - timedelta(days=30)
    w_end = anchor + timedelta(days=14)
    return anchor, w_start, w_end


async def add_timeline_from_candidate(
    session: AsyncSession,
    campaign_id: int,
    candidate_id: int,
    *,
    sequence_no: Optional[int] = None,
    target_weight_pct: float = 50.0,
    build_lead_days: Optional[int] = None,
) -> dict[str, Any]:
    cand = await session.get(RadarCandidate, candidate_id)
    if cand is None:
        raise ValueError(f"候选 {candidate_id} 不存在")
    camp = await session.get(Campaign, campaign_id)
    if camp is None:
        raise ValueError(f"Campaign {campaign_id} 不存在")

    anchor, w_start, w_end = _parse_catalyst_window(cand.catalyst_window)
    if sequence_no is None:
        mx = await session.scalar(
            select(CampaignTimeline.sequence_no)
            .where(CampaignTimeline.campaign_id == campaign_id)
            .order_by(CampaignTimeline.sequence_no.desc())
            .limit(1)
        )
        sequence_no = (mx or 0) + 1

    lead = build_lead_days if build_lead_days is not None else default_build_lead_days()
    row = CampaignTimeline(
        campaign_id=campaign_id,
        symbol=cand.symbol.zfill(6)[-6:],
        anchor_date=anchor,
        window_start=w_start,
        window_end=w_end,
        build_lead_days=lead,
        sequence_no=sequence_no,
        target_weight_pct=target_weight_pct,
        title=f"{cand.name} 爆发点",
        kind="catalyst",
        confirm_state="inferred",
        status="expected",
        candidate_id=candidate_id,
    )
    session.add(row)
    await session.flush()

    # 标的级：把该标的纳入路线图区（前向单向，不会回退已在 planning 的标的）
    await set_stage(session, cand.symbol.zfill(6)[-6:], "roadmap")
    await _refresh_feasibility(session, campaign_id)
    await session.flush()
    await session.refresh(row)
    return timeline_to_dict(row)


async def add_timeline_entry(
    session: AsyncSession,
    campaign_id: int,
    *,
    symbol: str,
    anchor_date: date,
    title: str,
    window_start: Optional[date] = None,
    window_end: Optional[date] = None,
    sequence_no: Optional[int] = None,
    target_weight_pct: float = 50.0,
    build_lead_days: Optional[int] = None,
) -> dict[str, Any]:
    sym = symbol.zfill(6)[-6:]
    w_start = window_start or (anchor_date - timedelta(days=30))
    w_end = window_end or (anchor_date + timedelta(days=14))
    if sequence_no is None:
        mx = await session.scalar(
            select(CampaignTimeline.sequence_no)
            .where(CampaignTimeline.campaign_id == campaign_id)
            .order_by(CampaignTimeline.sequence_no.desc())
            .limit(1)
        )
        sequence_no = (mx or 0) + 1
    lead = build_lead_days if build_lead_days is not None else default_build_lead_days()
    row = CampaignTimeline(
        campaign_id=campaign_id,
        symbol=sym,
        anchor_date=anchor_date,
        window_start=w_start,
        window_end=w_end,
        build_lead_days=lead,
        sequence_no=sequence_no,
        target_weight_pct=target_weight_pct,
        title=title,
        kind="catalyst",
        confirm_state="inferred",
        status="expected",
    )
    session.add(row)
    await session.flush()
    await _refresh_feasibility(session, campaign_id)
    await session.flush()
    await session.refresh(row)
    return timeline_to_dict(row)


async def _refresh_feasibility(session: AsyncSession, campaign_id: int) -> None:
    rows = list(
        await session.scalars(
            select(CampaignTimeline)
            .where(CampaignTimeline.campaign_id == campaign_id)
            .order_by(CampaignTimeline.sequence_no)
        )
    )
    nodes = [timeline_to_dict(r) for r in rows]
    evaluated = evaluate_timeline_feasibility(
        nodes, build_lead_days=default_build_lead_days()
    )
    by_id = {n["id"]: n for n in evaluated}
    for r in rows:
        ev = by_id.get(r.id, {})
        r.feasibility_flags = ev.get("feasibility_flags") or []
        r.advisories = ev.get("advisories") or []


async def list_campaign_timeline(
    session: AsyncSession, campaign_id: int
) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(CampaignTimeline)
        .where(CampaignTimeline.campaign_id == campaign_id)
        .order_by(CampaignTimeline.sequence_no, CampaignTimeline.anchor_date)
    )
    return [timeline_to_dict(r) for r in rows]


async def list_pending_next_waves(session: AsyncSession) -> list[dict[str, Any]]:
    """归档后 long 标的 · 下一波待规划。"""
    rows = await session.scalars(
        select(RegimeAssessment).where(
            RegimeAssessment.horizon_class.in_(("mid", "long_multiwave")),
            RegimeAssessment.next_wave_window.isnot(None),
        )
    )
    return [
        {
            "symbol": r.symbol,
            "campaign_id": r.campaign_id,
            "horizon_class": r.horizon_class,
            "next_wave_window": r.next_wave_window,
            "confirm_state": r.confirm_state,
        }
        for r in rows
    ]


async def assess_campaign_regime(
    session: AsyncSession,
    campaign_id: int,
    *,
    redis_client: Any = None,
) -> list[dict[str, Any]]:
    syms = await session.scalars(
        select(CampaignSymbol).where(CampaignSymbol.campaign_id == campaign_id)
    )
    out: list[dict[str, Any]] = []
    for s in syms:
        if not s.symbol:
            continue
        phase = None
        snap = s.analysis_snapshot or {}
        phase = snap.get("market_phase")
        row = await assess_symbol_regime(
            session,
            campaign_id,
            s.symbol,
            redis_client=redis_client,
            market_phase=phase,
        )
        freq = os.environ.get("ROADMAP_PATROL_FREQ", "monthly")
        if row.horizon_class in ("mid", "long_multiwave"):
            await ensure_regime_patrol(
                session,
                campaign_id,
                s.symbol,
                hypothesis=f"生命周期 {row.horizon_class} 代理假设待巡检确认",
                frequency=freq,
            )
        out.append(regime_to_dict(row))
    return out


async def archive_campaign_rolling(
    session: AsyncSession,
    campaign_id: int,
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    """本波归档（标的级）：了结标的 → archived；long_multiwave → 回流路线图 roadmap。

    标的级漏斗：归档作用于 executing 标的本身（或指定 symbol），**绝不**归档整个容器。
    """
    camp = await session.scalar(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .options(selectinload(Campaign.symbols))
    )
    if camp is None:
        raise ValueError(f"Campaign {campaign_id} 不存在")

    regimes = await session.scalars(
        select(RegimeAssessment).where(RegimeAssessment.campaign_id == campaign_id)
    )
    by_sym = {r.symbol: r for r in regimes}

    targets = []
    for s in camp.symbols or []:
        sym = (s.symbol or "").zfill(6)[-6:]
        if not sym:
            continue
        if symbol and sym != symbol.zfill(6)[-6:]:
            continue
        if not symbol and s.funnel_stage != "executing":
            continue
        targets.append(s)

    archived: list[str] = []
    rolled_back: list[str] = []
    for s in targets:
        sym = s.symbol.zfill(6)[-6:]
        reg = by_sym.get(sym)
        if reg and reg.horizon_class in ("mid", "long_multiwave"):
            # 长周期多波：回流路线图等待下一波（allow_backward）
            if not reg.next_wave_window:
                reg.next_wave_window = (
                    date.today().replace(year=date.today().year + 1, month=6, day=30).isoformat()
                )
            await set_stage(session, sym, "roadmap", allow_backward=True)
            rolled_back.append(sym)
        else:
            await set_stage(session, sym, "archived")
            archived.append(sym)

    await session.flush()
    return {
        "campaign_id": campaign_id,
        "archived_symbols": archived,
        "rolled_back_symbols": rolled_back,
        "next_wave_pending": len(rolled_back),
    }


def timeline_to_dict(t: CampaignTimeline) -> dict[str, Any]:
    return {
        "id": t.id,
        "campaign_id": t.campaign_id,
        "symbol": t.symbol,
        "anchor_date": t.anchor_date.isoformat() if t.anchor_date else None,
        "window_start": t.window_start.isoformat() if t.window_start else None,
        "window_end": t.window_end.isoformat() if t.window_end else None,
        "build_lead_days": t.build_lead_days,
        "sequence_no": t.sequence_no,
        "target_weight_pct": t.target_weight_pct,
        "title": t.title,
        "kind": t.kind,
        "confirm_state": t.confirm_state,
        "status": t.status,
        "feasibility_flags": t.feasibility_flags or [],
        "advisories": t.advisories or [],
        "candidate_id": t.candidate_id,
    }
