"""规划区 4 类证伪任务 verdict 引擎 + 证据落库 + 就绪度。

[Ref: step_16_规划中证伪与持续监控.md]
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import (
    CampaignSymbol,
    EventLog,
    HealthRecord,
    MonitorSubscription,
    StageArtifact,
)

logger = logging.getLogger(__name__)

FALSIFY_TYPES = frozenset({"moat", "niche", "catalyst", "risk"})

DEFAULT_HYPOTHESES: dict[str, str] = {
    "moat": "其产能/份额壁垒真实存在（P5/P6/P7 探针可验证）",
    "niche": "其处于产业链卡脖子关键节点/龙头地位",
    "catalyst": "关键利好将在预期窗口内兑现",
    "risk": "无财务造假/重大风险信号",
}

READINESS_OK_THRESHOLD = float(os.environ.get("READINESS_OK_RATE_THRESHOLD", "0.5"))


async def create_falsify_task(
    session: AsyncSession,
    campaign_id: int,
    symbol: str,
    falsify_type: str,
    *,
    hypothesis: Optional[str] = None,
    frequency: Optional[str] = None,
    indicator: Optional[str] = None,
    source: Optional[str] = None,
) -> MonitorSubscription:
    ft = falsify_type.strip().lower()
    if ft not in FALSIFY_TYPES:
        raise ValueError(f"falsify_type 须为 {sorted(FALSIFY_TYPES)} 之一")
    sym = symbol.zfill(6)[-6:]
    hyp = hypothesis or DEFAULT_HYPOTHESES[ft]
    freq = frequency or os.environ.get("FALSIFY_DEFAULT_FREQ", "weekly")
    ind = indicator or f"证伪监控 · {ft}"
    src = source or f"planning/falsify.py · {ft}"

    existing = await session.scalar(
        select(MonitorSubscription).where(
            MonitorSubscription.campaign_id == campaign_id,
            MonitorSubscription.symbol == sym,
            MonitorSubscription.falsify_type == ft,
            MonitorSubscription.hypothesis == hyp,
        )
    )
    if existing:
        return existing

    sub = MonitorSubscription(
        campaign_id=campaign_id,
        symbol=sym,
        pillar=ft,
        falsify_type=ft,
        hypothesis=hyp,
        indicator=ind,
        source=src,
        frequency=freq,
        verdict="pending",
    )
    session.add(sub)
    await session.flush()
    return sub


async def ensure_default_falsify_tasks(
    session: AsyncSession, campaign_id: int, symbol: str
) -> list[MonitorSubscription]:
    """为标的建 4 类证伪任务（若不存在）。"""
    created: list[MonitorSubscription] = []
    for ft in sorted(FALSIFY_TYPES):
        sub = await create_falsify_task(session, campaign_id, symbol, ft)
        created.append(sub)
    return created


async def list_falsify_tasks(
    session: AsyncSession,
    campaign_id: int,
    symbol: Optional[str] = None,
) -> list[dict[str, Any]]:
    q = select(MonitorSubscription).where(
        MonitorSubscription.campaign_id == campaign_id,
        MonitorSubscription.falsify_type.in_(tuple(FALSIFY_TYPES)),
    )
    if symbol:
        q = q.where(MonitorSubscription.symbol == symbol.zfill(6)[-6:])
    rows = await session.scalars(q.order_by(MonitorSubscription.falsify_type))
    return [_falsify_to_dict(m) for m in rows]


async def refresh_falsify_verdicts(
    session: AsyncSession, campaign_id: int, redis_client: Any
) -> int:
    """刷新 4 类证伪 verdict + 写 stage_artifacts(workspace=planning)。"""
    rows = list(
        await session.scalars(
            select(MonitorSubscription).where(
                MonitorSubscription.campaign_id == campaign_id,
                MonitorSubscription.falsify_type.in_(tuple(FALSIFY_TYPES)),
            )
        )
    )
    updated = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for sub in rows:
        verdict, evidence, payload = await _evaluate_falsify(
            session, redis_client, sub
        )
        if verdict != sub.verdict or sub.last_checked_at is None:
            sub.verdict = verdict
            sub.last_checked_at = now
            sub.evidence_ref = evidence
            updated += 1
        if payload:
            session.add(
                StageArtifact(
                    symbol=sub.symbol,
                    workspace="planning",
                    stage=f"falsify_{sub.falsify_type}",
                    model_id=payload.get("model_id", "code:falsify"),
                    payload_json=payload,
                    input_refs=[f"monitor_sub:{sub.id}"],
                )
            )
    return updated


async def _evaluate_falsify(
    session: AsyncSession,
    redis_client: Any,
    sub: MonitorSubscription,
) -> tuple[str, Optional[str], dict[str, Any]]:
    sym = (sub.symbol or "").zfill(6)[-6:]
    ft = sub.falsify_type or sub.pillar
    if not sym or ft not in FALSIFY_TYPES:
        return "pending", None, {}

    if ft == "moat":
        return _eval_falsify_moat(redis_client, sym, sub.hypothesis)
    if ft == "niche":
        return _eval_falsify_niche(redis_client, sym, sub.hypothesis)
    if ft == "catalyst":
        return _eval_falsify_catalyst(redis_client, sym, sub.hypothesis)
    if ft == "risk":
        return await _eval_falsify_risk(session, redis_client, sym, sub.hypothesis)
    return "pending", None, {}


def _eval_falsify_moat(
    redis_client: Any, symbol: str, hypothesis: Optional[str]
) -> tuple[str, Optional[str], dict[str, Any]]:
    try:
        from apps.state_watch.probes.monitor_dict_reader import MonitorDictReader

        reader = MonitorDictReader(redis_client)
        if not reader.has_dict(symbol):
            return "pending", None, {"reason": "no_monitor_dict", "hypothesis": hypothesis}

        hits: list[str] = []
        for probe in ("P5", "P6", "P7"):
            for f in reader.fields_for_probe(symbol, probe):
                raw = redis_client.get(f.raw_key)
                if not raw:
                    continue
                payload = json.loads(raw if isinstance(raw, str) else raw.decode())
                if payload.get("last_hit_at"):
                    hits.append(f"{probe}:{f.field_id}")
        if hits:
            ev = f"moat_hits={','.join(hits[:5])}"
            return "ok", ev, {"verdict": "ok", "hits": hits, "hypothesis": hypothesis, "model_id": "code:P5P6P7"}
        if reader.get_meta(symbol):
            return "warn", "dict_no_recent_hit", {
                "verdict": "warn",
                "hypothesis": hypothesis,
                "model_id": "code:P5P6P7",
            }
        return "pending", None, {"reason": "no_hits", "hypothesis": hypothesis}
    except Exception as exc:  # noqa: BLE001
        logger.debug("falsify moat %s: %s", symbol, exc)
        return "pending", None, {"error": str(exc)[:120]}


def _eval_falsify_niche(
    redis_client: Any, symbol: str, hypothesis: Optional[str]
) -> tuple[str, Optional[str], dict[str, Any]]:
    try:
        from apps.state_watch.probes.monitor_dict_reader import MonitorDictReader

        reader = MonitorDictReader(redis_client)
        if not reader.has_dict(symbol):
            return "pending", None, {"reason": "no_architect_chain", "hypothesis": hypothesis}

        nodes: list[str] = []
        for probe in ("P5", "P6", "P7"):
            for f in reader.fields_for_probe(symbol, probe):
                nodes.extend(f.mapped_logic_chain_nodes)
        unique = list(dict.fromkeys(nodes))[:8]
        meta = reader.get_meta(symbol) or {}
        if unique or meta.get("industry_chain_summary"):
            return "ok", f"niche_nodes={len(unique)}", {
                "verdict": "ok",
                "nodes": unique,
                "summary": meta.get("industry_chain_summary"),
                "hypothesis": hypothesis,
                "model_id": "code:architect_proxy",
            }
        return "pending", None, {"reason": "empty_niche", "hypothesis": hypothesis}
    except Exception as exc:  # noqa: BLE001
        return "pending", None, {"error": str(exc)[:120]}


def _eval_falsify_catalyst(
    redis_client: Any, symbol: str, hypothesis: Optional[str]
) -> tuple[str, Optional[str], dict[str, Any]]:
    try:
        stream = "events:thrust:thesis_proposed"
        entries = redis_client.xrevrange(stream, count=50) or []
        for _mid, fields in entries:
            raw = fields.get("json") or fields.get(b"json")
            if raw is None:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode()
            payload = json.loads(raw)
            if str(payload.get("symbol", "")).zfill(6)[-6:] != symbol:
                continue
            action = str(payload.get("action", "")).lower()
            if action in ("reject", "falsified", "invalid"):
                return "alert", f"thesis_falsified:{payload.get('event_id')}", {
                    "verdict": "alert",
                    "event_id": payload.get("event_id"),
                    "hypothesis": hypothesis,
                    "model_id": "code:sniffer",
                }
            return "ok", f"thesis_proposed:{payload.get('event_id')}", {
                "verdict": "ok",
                "event_id": payload.get("event_id"),
                "hypothesis": hypothesis,
                "model_id": "code:sniffer",
            }
        return "pending", None, {"reason": "no_catalyst_stream", "hypothesis": hypothesis}
    except Exception as exc:  # noqa: BLE001
        return "pending", None, {"error": str(exc)[:120]}


async def _eval_falsify_risk(
    session: AsyncSession,
    redis_client: Any,
    symbol: str,
    hypothesis: Optional[str],
) -> tuple[str, Optional[str], dict[str, Any]]:
    # 优先 FinancialFraudEngine（T1）
    try:
        from apps.cryo_guard.engines.financial_fraud.engine import FinancialFraudEngine
        from apps.cryo_guard.engines.financial_fraud.schemas import FraudLabel, RiskLevel

        engine = FinancialFraudEngine(vllm_url=os.environ.get("VLLM_BASE_URL"))
        report = engine.analyze(symbol, "latest")
        if report.history_insufficient or len(report.missing_fields) > 3:
            pass  # fall through to health/cryo
        elif report.label == FraudLabel.FRAUD or report.risk_level == RiskLevel.HIGH:
            return "alert", f"fraud_engine:{report.risk_level.value}", {
                "verdict": "alert",
                "label": report.label.value,
                "risk_level": report.risk_level.value,
                "hypothesis": hypothesis,
                "model_id": "t1:FinancialFraudEngine",
            }
        elif report.label == FraudLabel.NORMAL and report.risk_level in (
            RiskLevel.LOW,
            RiskLevel.MEDIUM,
        ):
            return "ok", f"fraud_engine:{report.risk_level.value}", {
                "verdict": "ok",
                "label": report.label.value,
                "risk_level": report.risk_level.value,
                "hypothesis": hypothesis,
                "model_id": "t1:FinancialFraudEngine",
            }
    except Exception as exc:  # noqa: BLE001
        logger.debug("fraud engine %s: %s", symbol, exc)

    hr = await session.scalar(
        select(HealthRecord)
        .where(HealthRecord.symbol == symbol)
        .order_by(HealthRecord.received_at.desc())
        .limit(1)
    )
    if hr is not None:
        if hr.push_level >= 3:
            return "alert", f"health_push={hr.push_level}", {
                "verdict": "alert",
                "push_level": hr.push_level,
                "hypothesis": hypothesis,
                "model_id": "code:health",
            }
        if hr.push_level >= 2:
            return "warn", f"health_push={hr.push_level}", {
                "verdict": "warn",
                "push_level": hr.push_level,
                "hypothesis": hypothesis,
                "model_id": "code:health",
            }
        return "ok", f"health={hr.new_health:.2f}", {
            "verdict": "ok",
            "health": hr.new_health,
            "hypothesis": hypothesis,
            "model_id": "code:health",
        }

    if redis_client is not None:
        try:
            for stream in ("events:cryo_guard:reject", "events:cryo_guard:degrade"):
                entries = redis_client.xrevrange(stream, count=30) or []
                for _mid, fields in entries:
                    raw = fields.get("json") or fields.get(b"json")
                    if raw is None:
                        continue
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    payload = json.loads(raw)
                    if str(payload.get("symbol", "")).zfill(6)[-6:] == symbol:
                        v = "alert" if "reject" in stream else "warn"
                        return v, stream, {
                            "verdict": v,
                            "stream": stream,
                            "hypothesis": hypothesis,
                            "model_id": "code:cryo_guard",
                        }
        except Exception:  # noqa: BLE001
            pass

    return "pending", None, {"reason": "risk_sources_unavailable", "hypothesis": hypothesis}


def compute_readiness(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """聚合 4 类证伪 verdict → 晋级就绪度（advisory）。"""
    core = [t for t in tasks if t.get("falsify_type") in FALSIFY_TYPES]
    if not core:
        return {
            "ok_rate": 0.0,
            "falsified": 0,
            "pending": 0,
            "total": 0,
            "advice": "尚未建立证伪任务，请先 POST /falsify 或经雷达晋级",
            "human_confirmation_required": True,
            "ready_for_executing": False,
        }

    ok_n = sum(1 for t in core if t.get("verdict") == "ok")
    alert_n = sum(1 for t in core if t.get("verdict") == "alert")
    pending_n = sum(1 for t in core if t.get("verdict") == "pending")
    total = len(core)
    ok_rate = ok_n / total if total else 0.0
    ready = ok_rate >= READINESS_OK_THRESHOLD and alert_n == 0 and pending_n < total

    if alert_n:
        advice = f"有 {alert_n} 条论点被证伪（alert），不建议晋级执行"
    elif pending_n == total:
        advice = "全部证伪任务缺源 pending，请补齐数据后再评估"
    elif ready:
        advice = "就绪度达标（advisory），可人工确认晋级执行"
    else:
        advice = f"成立率 {ok_rate:.0%} 未达阈值 {READINESS_OK_THRESHOLD:.0%}，继续监控"

    return {
        "ok_rate": round(ok_rate, 4),
        "falsified": alert_n,
        "pending": pending_n,
        "warn": sum(1 for t in core if t.get("verdict") == "warn"),
        "total": total,
        "advice": advice,
        "human_confirmation_required": True,
        "ready_for_executing": ready,
    }


async def get_cognitive_snapshot(
    session: AsyncSession,
    campaign_id: int,
    symbol: str,
) -> dict[str, Any]:
    """认知快照：analysis_snapshot + 溯源 artifact 链接。"""
    sym = symbol.zfill(6)[-6:]
    row = await session.scalar(
        select(CampaignSymbol).where(
            CampaignSymbol.campaign_id == campaign_id,
            CampaignSymbol.symbol == sym,
        )
    )
    if row is None:
        return {"symbol": sym, "status": "missing", "message": "标的不在 Campaign 中"}

    snapshot = row.analysis_snapshot
    artifact_refs: list[dict[str, Any]] = []
    if row.promoted_from_candidate_id:
        arts = await session.scalars(
            select(StageArtifact).where(
                StageArtifact.candidate_id == row.promoted_from_candidate_id,
                StageArtifact.workspace == "radar",
            )
        )
        for a in arts:
            artifact_refs.append(
                {
                    "id": a.id,
                    "stage": a.stage,
                    "workspace": a.workspace,
                    "model_id": a.model_id,
                    "produced_at": a.produced_at.isoformat() if a.produced_at else None,
                }
            )

    if not snapshot:
        return {
            "symbol": sym,
            "name": row.name,
            "status": "empty",
            "message": "无认知快照 · 请先经雷达扫描 promote",
            "artifact_refs": artifact_refs,
        }

    return {
        "symbol": sym,
        "name": row.name,
        "status": "ok",
        "analysis_snapshot": snapshot,
        "promoted_from_candidate_id": row.promoted_from_candidate_id,
        "artifact_refs": artifact_refs,
    }


def _falsify_to_dict(m: MonitorSubscription) -> dict[str, Any]:
    return {
        "id": m.id,
        "campaign_id": m.campaign_id,
        "symbol": m.symbol,
        "falsify_type": m.falsify_type or m.pillar,
        "hypothesis": m.hypothesis,
        "indicator": m.indicator,
        "source": m.source,
        "frequency": m.frequency,
        "verdict": m.verdict,
        "last_checked_at": m.last_checked_at.isoformat() if m.last_checked_at else None,
        "evidence_ref": m.evidence_ref,
    }
