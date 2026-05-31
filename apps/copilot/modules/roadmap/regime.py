"""维度二 · 行情生命周期判定（启动期 thesis/Timer 代理 · 全 inferred）。

[Ref: step_15 §3.2]
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from apps.copilot.db.models import RegimeAssessment, ThesisCard

HORIZON_MAP = {
    "short": "short",
    "mid": "mid",
    "medium": "mid",
    "long": "long_multiwave",
    "long_multiwave": "long_multiwave",
}

PHASE_TO_HORIZON = {
    "concept": "short",
    "expectation": "short",
    "realization": "mid",
    "exhaustion": "single",
}


def classify_horizon_from_proxy(
    *,
    thesis_horizon: Optional[str] = None,
    market_phase: Optional[str] = None,
    timer_regime: Optional[str] = None,
) -> tuple[str, str, dict[str, Any]]:
    """返回 (horizon_class, confirm_state, proxy_sources)。"""
    sources: dict[str, Any] = {}
    hc: Optional[str] = None

    if thesis_horizon:
        th = thesis_horizon.strip().lower()
        hc = HORIZON_MAP.get(th, "single")
        sources["thesis_horizon"] = thesis_horizon

    if market_phase and market_phase not in ("pending", "unknown", ""):
        ph = market_phase.strip().lower()
        phase_h = PHASE_TO_HORIZON.get(ph)
        if phase_h:
            sources["market_phase"] = market_phase
            if hc is None:
                hc = phase_h
            elif phase_h == "long_multiwave" or (hc == "single" and phase_h != "single"):
                hc = phase_h

    if timer_regime:
        sources["timer_regime"] = timer_regime
        tr = timer_regime.strip().lower()
        if "long" in tr or "multi" in tr:
            hc = "long_multiwave"
        elif "mid" in tr and hc in (None, "single", "short"):
            hc = "mid"

    if hc is None:
        hc = "single"
        sources["default"] = "single"

    wave_est = {"single": 1, "short": 1, "mid": 2, "long_multiwave": 4}.get(hc, 1)
    duration = {
        "single": "单次",
        "short": "1~2月",
        "mid": "2~3年多波",
        "long_multiwave": "5~8年多波",
    }.get(hc, "未知")

    return hc, "inferred", {
        "proxy_sources": sources,
        "wave_count_est": wave_est,
        "duration_est": duration,
    }


async def load_thesis_horizon(session: AsyncSession, symbol: str) -> Optional[str]:
    sym = symbol.zfill(6)[-6:]
    card = await session.scalar(
        select(ThesisCard)
        .where(ThesisCard.symbol == sym)
        .order_by(ThesisCard.proposed_at.desc())
        .limit(1)
    )
    if not card:
        return None
    anchor = card.valuation_anchor or {}
    if isinstance(anchor, str):
        try:
            anchor = json.loads(anchor)
        except json.JSONDecodeError:
            anchor = {}
    return anchor.get("horizon") or anchor.get("investment_horizon")


def load_timer_regime(redis_client: Any, symbol: str) -> Optional[str]:
    if redis_client is None:
        return None
    sym = symbol.zfill(6)[-6:]
    try:
        for stream in ("events:deep_strike:timer_signal",):
            entries = redis_client.xrevrange(stream, count=80) or []
            for _mid, fields in entries:
                raw = fields.get("json") or fields.get(b"json")
                if raw is None:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode()
                payload = json.loads(raw)
                if str(payload.get("symbol", "")).zfill(6)[-6:] != sym:
                    continue
                meta = payload.get("timer_meta") or payload.get("regime") or {}
                if isinstance(meta, dict):
                    return meta.get("horizon") or meta.get("regime_class")
                return str(meta) if meta else None
    except Exception:  # noqa: BLE001
        return None
    return None


async def assess_symbol_regime(
    session: AsyncSession,
    campaign_id: int,
    symbol: str,
    *,
    redis_client: Any = None,
    market_phase: Optional[str] = None,
) -> RegimeAssessment:
    sym = symbol.zfill(6)[-6:]
    thesis_h = await load_thesis_horizon(session, sym)
    timer_r = load_timer_regime(redis_client, sym)
    snap_phase = market_phase
    snap_thesis: Optional[str] = None
    if snap_phase is None or thesis_h is None:
        from apps.copilot.db.models import CampaignSymbol

        cs = await session.scalar(
            select(CampaignSymbol).where(
                CampaignSymbol.campaign_id == campaign_id,
                CampaignSymbol.symbol == sym,
            )
        )
        if cs and cs.analysis_snapshot:
            snap = cs.analysis_snapshot
            snap_phase = snap_phase or snap.get("market_phase")
            snap_thesis = snap.get("thesis_horizon")
    if thesis_h is None and snap_thesis:
        thesis_h = snap_thesis
    hc, confirm, meta = classify_horizon_from_proxy(
        thesis_horizon=thesis_h,
        market_phase=snap_phase,
        timer_regime=timer_r,
    )

    existing = await session.scalar(
        select(RegimeAssessment).where(
            RegimeAssessment.campaign_id == campaign_id,
            RegimeAssessment.symbol == sym,
        )
    )
    next_wave = None
    if hc in ("mid", "long_multiwave"):
        next_wave = date.today().replace(year=date.today().year + 1, month=6, day=30)

    if existing:
        existing.horizon_class = hc
        existing.wave_count_est = meta["wave_count_est"]
        existing.duration_est = meta["duration_est"]
        existing.confirm_state = confirm
        existing.proxy_sources = meta.get("proxy_sources")
        if next_wave:
            existing.next_wave_window = next_wave.isoformat()
        row = existing
    else:
        row = RegimeAssessment(
            campaign_id=campaign_id,
            symbol=sym,
            horizon_class=hc,
            wave_count_est=meta["wave_count_est"],
            duration_est=meta["duration_est"],
            confirm_state=confirm,
            proxy_sources=meta.get("proxy_sources"),
            next_wave_window=next_wave.isoformat() if next_wave else None,
        )
        session.add(row)
    await session.flush()
    return row


def regime_to_dict(r: RegimeAssessment) -> dict[str, Any]:
    return {
        "id": r.id,
        "campaign_id": r.campaign_id,
        "symbol": r.symbol,
        "horizon_class": r.horizon_class,
        "wave_count_est": r.wave_count_est,
        "duration_est": r.duration_est,
        "confirm_state": r.confirm_state,
        "proxy_sources": r.proxy_sources,
        "next_wave_window": r.next_wave_window,
    }
