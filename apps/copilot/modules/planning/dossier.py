"""6 维分析档案聚合：行情/阶段/生态位/壁垒/风险/监控。

[Ref: 24_行情解析与规划工作台_需求实现表.md · 必做③]
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import CampaignSymbol, EventLog, HealthRecord, ThesisCard
from apps.copilot.modules.planning.falsify import (
    compute_readiness,
    get_cognitive_snapshot,
    list_falsify_tasks,
)
from apps.copilot.modules.planning.monitor import (
    PHASE_LABELS,
    list_monitors,
    refresh_verdicts,
)

logger = logging.getLogger(__name__)

PENDING = {"status": "pending", "label": "待接入", "as_of": None}


async def build_symbol_dossier(
    session: AsyncSession,
    campaign_id: int,
    symbol: str,
    *,
    redis_client: Any = None,
) -> dict[str, Any]:
    """构建单标的 6 维分析档案；缺上游显式 pending。"""
    from apps.copilot.services.redis_wait import wait_for_sync_redis

    if redis_client is None:
        redis_client = wait_for_sync_redis()

    sym = symbol.zfill(6)[-6:]
    row = await session.scalar(
        select(CampaignSymbol).where(
            CampaignSymbol.campaign_id == campaign_id,
            CampaignSymbol.symbol == sym,
        )
    )
    name = row.name if row else sym

    await refresh_verdicts(session, campaign_id, redis_client)

    quote = await _build_quote(session, redis_client, sym)
    phase = await _build_phase(session, redis_client, sym)
    niche = _build_niche(redis_client, sym)
    moat = _build_moat(redis_client, sym)
    risk = await _build_risk(session, redis_client, sym)
    monitors = await list_monitors(session, campaign_id, sym)
    cognitive = await get_cognitive_snapshot(session, campaign_id, sym)
    falsify_tasks = await list_falsify_tasks(session, campaign_id, sym)
    readiness = compute_readiness(falsify_tasks)

    return {
        "symbol": sym,
        "name": name,
        "campaign_id": campaign_id,
        "quote": quote,
        "phase": phase,
        "niche": niche,
        "moat": moat,
        "risk": risk,
        "monitors": monitors,
        "cognitive_snapshot": cognitive,
        "falsify_tasks": falsify_tasks,
        "readiness": readiness,
    }


async def _build_quote(
    session: AsyncSession, redis_client: Any, symbol: str
) -> dict[str, Any]:
    """① 当前行情：D4 quote / D3 PhaseSignals（轻量拉取，超时则 pending）。"""
    try:
        from apps.state_watch.market_phase.signal_builder import extended_price_metrics
        from apps.state_watch.probes.datasource.quote_adapter import fetch_bars_60d

        bars = await asyncio.wait_for(asyncio.to_thread(fetch_bars_60d, symbol), timeout=5.0)
        if not bars:
            return {**PENDING, "detail": "行情数据不足"}
        price = extended_price_metrics(bars)
        if price.get("insufficient_price"):
            return {**PENDING, "detail": "行情数据不足"}
        return {
            "status": "ok",
            "pct_chg_1d": price.get("pct_change_1d"),
            "pct_chg_5d": price.get("pct_chg_5d"),
            "pct_chg_30d": price.get("pct_chg_30d"),
            "volume_ratio_5d": price.get("volume_ratio_5d"),
            "as_of": datetime.utcnow().isoformat(),
        }
    except asyncio.TimeoutError:
        return {**PENDING, "detail": "行情拉取超时"}
    except Exception as exc:  # noqa: BLE001
        logger.debug("quote build %s: %s", symbol, exc)
        return {**PENDING, "detail": str(exc)[:120]}


async def _build_phase(
    session: AsyncSession, redis_client: Any, symbol: str
) -> dict[str, Any]:
    """② 所处阶段：D3 market_phase + D2 Timer。"""
    mp = None
    conf = None
    tags: list[str] = []

    ev = await session.scalar(
        select(EventLog)
        .where(
            EventLog.symbol == symbol,
            EventLog.event_type == "market_phase_change",
        )
        .order_by(EventLog.received_at.desc())
        .limit(1)
    )
    if ev and ev.payload:
        mp = ev.payload.get("market_phase")
        conf = ev.payload.get("market_phase_confidence")
        tags = ev.payload.get("reasoning_tags") or []

    if mp is None and redis_client is not None:
        try:
            raw = redis_client.get(f"market_phase:{symbol}")
            if raw:
                data = json.loads(raw if isinstance(raw, str) else raw.decode())
                mp = data.get("market_phase")
                conf = data.get("confidence")
        except Exception:  # noqa: BLE001
            pass

    timer_stage = None
    thesis = await session.scalar(
        select(ThesisCard)
        .where(ThesisCard.symbol == symbol)
        .order_by(ThesisCard.proposed_at.desc())
        .limit(1)
    )
    if thesis and isinstance(thesis.valuation_anchor, dict):
        timer_stage = thesis.valuation_anchor.get("timer_signal") or thesis.valuation_anchor.get(
            "stage"
        )

    if mp is None and timer_stage is None:
        return {**PENDING, "market_phase": None, "timer": None}

    label = PHASE_LABELS.get(str(mp), mp) if mp else None
    return {
        "status": "ok" if mp else "pending",
        "market_phase": mp,
        "market_phase_label": label,
        "confidence": conf,
        "reasoning_tags": tags,
        "timer": timer_stage,
        "as_of": datetime.utcnow().isoformat(),
    }


def _build_niche(redis_client: Any, symbol: str) -> dict[str, Any]:
    """③ 产业生态位：monitor:dict + related_party_graph。"""
    if redis_client is None:
        return {**PENDING, "text": "待生态位分析"}

    try:
        from apps.state_watch.probes.monitor_dict_reader import MonitorDictReader

        reader = MonitorDictReader(redis_client)
        if not reader.has_dict(symbol):
            return {**PENDING, "text": "待生态位分析"}

        meta = reader.get_meta(symbol) or {}
        chain_nodes: list[str] = []
        for probe in ("P5", "P6", "P7"):
            for f in reader.fields_for_probe(symbol, probe):
                chain_nodes.extend(f.mapped_logic_chain_nodes)
        unique_nodes = list(dict.fromkeys(chain_nodes))[:8]
        text = meta.get("industry_chain_summary") or meta.get("theme") or ""
        if unique_nodes:
            text = (text + " · 产业链节点：" + " / ".join(unique_nodes)).strip(" · ")
        if text:
            return {"status": "ok", "text": text, "nodes": unique_nodes, "as_of": datetime.utcnow().isoformat()}
        return {"status": "warn", "text": "监控字典已就绪，生态位摘要待补", "nodes": unique_nodes}
    except Exception as exc:  # noqa: BLE001
        logger.debug("niche %s: %s", symbol, exc)
        return {**PENDING, "text": "待生态位分析"}


def _build_moat(redis_client: Any, symbol: str) -> dict[str, Any]:
    """④ 核心壁垒：P5/P6/P7 + monitor:dict。"""
    if redis_client is None:
        return {**PENDING, "probes": {}}

    try:
        from apps.state_watch.probes.monitor_dict_reader import MonitorDictReader

        reader = MonitorDictReader(redis_client)
        if not reader.has_dict(symbol):
            return {**PENDING, "probes": {}}

        probes: dict[str, Any] = {}
        for probe in ("P5", "P6", "P7"):
            fields = reader.fields_for_probe(symbol, probe)
            probes[probe] = {
                "field_count": len(fields),
                "metrics": [f.metric_name for f in fields[:3]],
            }
        if any(v["field_count"] > 0 for v in probes.values()):
            return {"status": "ok", "probes": probes, "as_of": datetime.utcnow().isoformat()}
        return {"status": "pending", "probes": probes}
    except Exception as exc:  # noqa: BLE001
        logger.debug("moat %s: %s", symbol, exc)
        return {**PENDING, "probes": {}}


async def _build_risk(
    session: AsyncSession, redis_client: Any, symbol: str
) -> dict[str, Any]:
    """⑤ 关键风险：D1 decision_gate + D3 health_change。"""
    hr = await session.scalar(
        select(HealthRecord)
        .where(HealthRecord.symbol == symbol)
        .order_by(HealthRecord.received_at.desc())
        .limit(1)
    )
    if hr:
        status = "alert" if hr.push_level >= 3 else ("warn" if hr.push_level >= 2 else "ok")
        return {
            "status": status,
            "health_score": hr.new_health,
            "push_level": hr.push_level,
            "change_reason": hr.change_reason,
            "source": "health_records",
            "as_of": hr.received_at.isoformat(),
        }

    if redis_client is not None:
        try:
            for stream, label in (
                ("events:cryo_guard:reject", "reject"),
                ("events:cryo_guard:degrade", "degrade"),
                ("events:cryo_guard:pass", "pass"),
            ):
                entries = redis_client.xrevrange(stream, count=20) or []
                for _mid, fields in entries:
                    raw = fields.get("json") or fields.get(b"json")
                    if raw is None:
                        continue
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    payload = json.loads(raw)
                    if str(payload.get("symbol", "")).zfill(6)[-6:] == symbol:
                        st = "alert" if label == "reject" else ("warn" if label == "degrade" else "ok")
                        return {
                            "status": st,
                            "decision_gate": label,
                            "source": stream,
                            "as_of": datetime.utcnow().isoformat(),
                        }
        except Exception:  # noqa: BLE001
            pass

    return {**PENDING, "health_score": None, "decision_gate": None}
