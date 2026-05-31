"""三支柱监控订阅：moat / catalyst / risk。

[Ref: 03_/00_维度零/.../step_12_行情解析与规划工作台.md §3.2]
[Ref: 24_行情解析与规划工作台_需求实现表.md · 必做④]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import EventLog, HealthRecord, MonitorSubscription

from apps.copilot.modules.planning.falsify import FALSIFY_TYPES, refresh_falsify_verdicts

logger = logging.getLogger(__name__)

DEFAULT_PILLAR_INDICATORS: dict[str, tuple[str, str]] = {
    "moat": ("物理量探针 P5/P6/P7", "D3 monitor:dict + physical_probes"),
    "catalyst": ("利好嗅探三源", "D2 Sniffer"),
    "risk": ("健康度 + 极寒防御", "D3 health_change + D1 decision_gate"),
}

PHASE_LABELS = {
    "concept": "概念",
    "expectation": "预期",
    "realization": "兑现",
    "exhaustion": "退潮",
}


async def ensure_regime_patrol(
    session: AsyncSession,
    campaign_id: int,
    symbol: str,
    *,
    hypothesis: str,
    frequency: str = "monthly",
) -> MonitorSubscription:
    """长周期 regime 巡检订阅（step_15 · pillar=regime）。"""
    sym = symbol.zfill(6)[-6:]
    existing = await session.scalar(
        select(MonitorSubscription).where(
            MonitorSubscription.campaign_id == campaign_id,
            MonitorSubscription.symbol == sym,
            MonitorSubscription.pillar == "regime",
        )
    )
    if existing:
        existing.hypothesis = hypothesis
        existing.frequency = frequency
        existing.falsify_type = "regime"
        return existing
    sub = MonitorSubscription(
        campaign_id=campaign_id,
        symbol=sym,
        pillar="regime",
        falsify_type="regime",
        hypothesis=hypothesis,
        indicator="长周期生命周期巡检",
        source="roadmap/regime.py · thesis+Timer 代理",
        frequency=frequency,
        verdict="pending",
    )
    session.add(sub)
    return sub


async def ensure_three_pillars(
    session: AsyncSession, campaign_id: int, symbol: str
) -> list[MonitorSubscription]:
    """每只标的确保 moat/catalyst/risk 各 1 条订阅。"""
    sym = symbol.zfill(6)[-6:]
    existing = await session.scalars(
        select(MonitorSubscription).where(
            MonitorSubscription.campaign_id == campaign_id,
            MonitorSubscription.symbol == sym,
        )
    )
    by_pillar = {m.pillar: m for m in existing}
    created: list[MonitorSubscription] = []
    for pillar, (indicator, source) in DEFAULT_PILLAR_INDICATORS.items():
        if pillar in by_pillar:
            continue
        sub = MonitorSubscription(
            campaign_id=campaign_id,
            symbol=sym,
            pillar=pillar,
            falsify_type=pillar,
            hypothesis=None,
            indicator=indicator,
            source=source,
            frequency="daily" if pillar != "catalyst" else "weekly",
            verdict="pending",
        )
        session.add(sub)
        created.append(sub)
    return created


async def list_monitors(
    session: AsyncSession, campaign_id: int, symbol: Optional[str] = None
) -> list[dict[str, Any]]:
    q = select(MonitorSubscription).where(
        MonitorSubscription.campaign_id == campaign_id
    )
    if symbol:
        q = q.where(MonitorSubscription.symbol == symbol.zfill(6)[-6:])
    rows = await session.scalars(q.order_by(MonitorSubscription.pillar))
    return [_monitor_to_dict(m) for m in rows]


async def refresh_verdicts(
    session: AsyncSession, campaign_id: int, redis_client: Any
) -> int:
    """周期采集判定：有真实上游则更新 verdict，缺则保持 pending。"""
    rows = list(
        await session.scalars(
            select(MonitorSubscription).where(
                MonitorSubscription.campaign_id == campaign_id
            )
        )
    )
    updated = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for sub in rows:
        ft = sub.falsify_type or ""
        if ft in FALSIFY_TYPES:
            continue
        verdict, evidence = await _evaluate_pillar(
            session, redis_client, sub.pillar, sub.symbol or ""
        )
        if verdict != sub.verdict or sub.last_checked_at is None:
            sub.verdict = verdict
            sub.last_checked_at = now
            sub.evidence_ref = evidence
            updated += 1
    updated += await refresh_falsify_verdicts(session, campaign_id, redis_client)
    return updated


async def _evaluate_pillar(
    session: AsyncSession,
    redis_client: Any,
    pillar: str,
    symbol: str,
) -> tuple[str, Optional[str]]:
    sym = symbol.zfill(6)[-6:] if symbol else ""
    if not sym:
        return "pending", None

    if pillar == "moat":
        return _eval_moat(redis_client, sym)
    if pillar == "catalyst":
        return _eval_catalyst(redis_client, sym)
    if pillar == "risk":
        return await _eval_risk(session, redis_client, sym)
    if pillar == "regime":
        return "pending", "regime_patrol_scheduled"
    return "pending", None


def _eval_moat(redis_client: Any, symbol: str) -> tuple[str, Optional[str]]:
    try:
        from apps.state_watch.probes.monitor_dict_reader import MonitorDictReader

        reader = MonitorDictReader(redis_client)
        if not reader.has_dict(symbol):
            return "pending", None
        hits = []
        for probe in ("P5", "P6", "P7"):
            fields = reader.fields_for_probe(symbol, probe)
            for f in fields:
                raw = redis_client.get(f.raw_key)
                if not raw:
                    continue
                payload = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
                if payload.get("last_hit_at"):
                    hits.append(f"{probe}:{f.field_id}")
        if hits:
            return "ok", f"monitor_dict hits={','.join(hits[:3])}"
        meta = reader.get_meta(symbol)
        if meta:
            return "warn", "monitor_dict present, no recent probe hit"
        return "pending", None
    except Exception as exc:  # noqa: BLE001
        logger.debug("moat eval %s: %s", symbol, exc)
        return "pending", None


def _eval_catalyst(redis_client: Any, symbol: str) -> tuple[str, Optional[str]]:
    try:
        stream = "events:thrust:thesis_proposed"
        entries = redis_client.xrevrange(stream, count=50) or []
        for _msg_id, fields in entries:
            raw = fields.get("json") or fields.get(b"json")
            if raw is None:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode()
            payload = json.loads(raw)
            if str(payload.get("symbol", "")).zfill(6)[-6:] == symbol:
                return "ok", f"thesis_proposed:{payload.get('event_id', '')}"
        return "pending", None
    except Exception as exc:  # noqa: BLE001
        logger.debug("catalyst eval %s: %s", symbol, exc)
        return "pending", None


async def _eval_risk(
    session: AsyncSession, redis_client: Any, symbol: str
) -> tuple[str, Optional[str]]:
    hr = await session.scalar(
        select(HealthRecord)
        .where(HealthRecord.symbol == symbol)
        .order_by(HealthRecord.received_at.desc())
        .limit(1)
    )
    if hr is not None:
        if hr.push_level >= 3:
            return "alert", f"health_change push_level={hr.push_level}"
        if hr.push_level >= 2:
            return "warn", f"health_change push_level={hr.push_level}"
        return "ok", f"health_score={hr.new_health:.2f}"

    try:
        for stream in ("events:cryo_guard:reject", "events:cryo_guard:degrade"):
            entries = redis_client.xrevrange(stream, count=30) or []
            for _msg_id, fields in entries:
                raw = fields.get("json") or fields.get(b"json")
                if raw is None:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode()
                payload = json.loads(raw)
                if str(payload.get("symbol", "")).zfill(6)[-6:] == symbol:
                    return "warn" if "degrade" in stream else "alert", stream
    except Exception:  # noqa: BLE001
        pass

    ev = await session.scalar(
        select(EventLog)
        .where(EventLog.symbol == symbol, EventLog.event_type == "health_change")
        .order_by(EventLog.received_at.desc())
        .limit(1)
    )
    if ev:
        pl = (ev.payload or {}).get("push_level", 0)
        return ("warn" if pl >= 2 else "ok"), f"event_log health_change"

    return "pending", None


def _monitor_to_dict(m: MonitorSubscription) -> dict[str, Any]:
    falsify = m.falsify_type or (m.pillar if m.pillar == "regime" else None)
    return {
        "id": m.id,
        "campaign_id": m.campaign_id,
        "symbol": m.symbol,
        "pillar": m.pillar,
        "falsify_type": falsify,
        "hypothesis": m.hypothesis,
        "indicator": m.indicator,
        "source": m.source,
        "frequency": m.frequency,
        "verdict": m.verdict,
        "last_checked_at": m.last_checked_at.isoformat() if m.last_checked_at else None,
        "evidence_ref": m.evidence_ref,
    }
