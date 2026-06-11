"""DeepSea 纯语义状态机 · fii_gb200_milestone。

[Ref: 28_ §2.2.1 · 29_ §5.4 · DeepSea V2.1 全栈拆解]
"""
from __future__ import annotations

import logging
import re
from typing import Any

from apps.copilot.modules.executing.l3.fii_gb200_milestone.constants import (
    CACHE_GROUP,
    LIFECYCLE_ORDER,
    NPI_STATE_DICTIONARY,
    PROBE_KEY,
    upstream_bottleneck_date,
)
from apps.copilot.modules.executing.l3.fii_gb200_milestone.t1_solver_lifecycle import (
    _combined_text,
    _parse_event_date,
    check_temporal_paradox,
    detect_lifecycle_stage,
    detect_state_transition,
)
from apps.copilot.services.deepsea.config_loader import get_l3_probe_config
from apps.copilot.services.deepsea.semantic_runner import call_semantic_json

logger = logging.getLogger(__name__)

_STATE_NODES = list(LIFECYCLE_ORDER)
_DEFAULT_CONCEPT = (
    "GB200/NVL72 客户验证进度、测试损耗、出货节奏（全文穷举拼图）"
)


def _prior_signal_status(t0: dict[str, Any]) -> str | None:
    snap = t0.get("prior_signal_snapshot")
    if isinstance(snap, dict) and snap.get("signal_status"):
        return str(snap["signal_status"]).strip().upper()
    prior = str(t0.get("prior_lifecycle_stage") or "").strip().upper()
    return prior or None


def _raw_inventory_qoq(t0: dict[str, Any]) -> float | None:
    shadow = t0.get("shadow_proxies") if isinstance(t0.get("shadow_proxies"), dict) else {}
    raw_m = shadow.get("raw_materials_inventory") if isinstance(shadow.get("raw_materials_inventory"), dict) else {}
    if raw_m.get("qoq_pct") is not None:
        return float(raw_m["qoq_pct"])
    return None


def build_shadow_validation(t0: dict[str, Any], *, signal_status: str) -> dict[str, Any]:
    """侧翼验真 · 原材料备料 + 语义 MP 节点。"""
    qoq = _raw_inventory_qoq(t0)
    applied = signal_status == "MP"
    passed = applied and qoq is not None and qoq >= 30.0
    note = (
        f"侧翼验真：本期原材料备料环比增幅 {qoq:.1f}%，支撑超级机柜大单物料吞吐特征，语义与财务硬数据印证成立。"
        if passed and qoq is not None
        else (
            f"侧翼验真：signal_status={signal_status}；原材料 QoQ={qoq if qoq is not None else '—'}%，"
            "未达 MP+备料共振阈值 30%。"
        )
    )
    return {
        "applied": applied,
        "cross_refs": ["fii_raw_inventory", "fii_copper_shfe"],
        "passed": passed,
        "note": note,
    }


def _probe_routing_config(t0: dict[str, Any]) -> dict[str, Any]:
    sym = str(t0.get("symbol") or "601138")
    try:
        return get_l3_probe_config(sym, PROBE_KEY)
    except (FileNotFoundError, KeyError):
        return {}


def _concept_probe_lines(cfg: dict[str, Any]) -> str:
    probes = cfg.get("concept_probes") or [_DEFAULT_CONCEPT]
    if isinstance(probes, str):
        probes = [probes]
    return "\n".join(f"- {p}" for p in probes if str(p).strip())


def needs_pro_review(parsed: dict[str, Any]) -> bool:
    """Flash 证据不足或 MP 跃迁置信偏低时拉起 Pro 复核。"""
    conf = str(parsed.get("confidence") or "medium").strip().lower()
    quotes = parsed.get("evidence_quotes") or []
    if isinstance(quotes, str):
        quotes = [quotes]
    status = str(parsed.get("signal_status") or "UNKNOWN").strip().upper()
    if conf == "low":
        return True
    if status in ("MP", "PVT") and len([q for q in quotes if str(q).strip()]) < 2:
        return True
    if status == "MP" and conf != "high":
        return True
    return False


def _rule_fallback_semantic(t0: dict[str, Any]) -> dict[str, Any]:
    """无 API Key 时 · 关键词状态机 + 多句证据拼装。"""
    text = _combined_text(t0)
    stage_key, stage_label, terms = detect_lifecycle_stage(text)
    prior = _prior_signal_status(t0)
    transition = detect_state_transition(prior, stage_key) if stage_key else None
    quotes: list[str] = []
    for chunk in re.split(r"[。！？\n]", text):
        s = chunk.strip()
        if not s or len(s) < 8:
            continue
        if any(t in s for t in terms) or any(k in s for k in ("GB200", "NVL", "量产", "交付", "验证")):
            quotes.append(s[:512])
        if len(quotes) >= 3:
            break
    if not quotes and text.strip():
        quotes.append(text.strip()[:512])

    momentum = "unknown"
    rationale = "无历史状态快照。"
    if prior and stage_key:
        pi = _STATE_NODES.index(prior) if prior in _STATE_NODES else -1
        ci = _STATE_NODES.index(stage_key) if stage_key in _STATE_NODES else -1
        if ci > pi:
            momentum = "accelerating"
            rationale = f"对比上期 {prior}，本期证据指向 {stage_key}，阶段跃迁走强。"
        elif ci == pi:
            momentum = "stalled"
            rationale = f"对比上期 {prior}，本期仍为 {stage_key}，边际停滞。"
        elif ci < pi:
            momentum = "reversed"
            rationale = f"对比上期 {prior}，本期回落至 {stage_key}，边际逆转。"

    status = stage_key or "UNKNOWN"
    fact = (
        f"官方文本交叉印证 GB200/NVL 进度，物理状态机节点为 {stage_label or status}。"
        if status != "UNKNOWN"
        else "语料未命中明确 NPI 节点。"
    )
    return {
        "llm_tag": "rule_fallback_keyword",
        "signal_status": status,
        "evidence_quotes": quotes,
        "fact_statement": fact,
        "momentum_delta": momentum,
        "momentum_rationale": rationale,
        "state_transition": transition,
        "lifecycle_stage_label": stage_label,
        "confidence": "medium" if quotes else "low",
    }


def _build_prompt(t0: dict[str, Any], *, prior_status: str | None, cfg: dict[str, Any]) -> str:
    doc_id = str(t0.get("doc_id") or t0.get("adjunct_url") or "cninfo_event")
    doc_type = str(t0.get("doc_type") or "cninfo_announcement")
    full_text = _combined_text(t0)
    upstream = upstream_bottleneck_date()
    nodes = " · ".join(cfg.get("state_machine_nodes") or _STATE_NODES)
    prior_line = prior_status or "无（首期）"
    concept_block = _concept_probe_lines(cfg)

    return f"""你是工业富联(601138) GB200/NVL72 量产节点语义分析师（DeepSea V2.1 · 纯语义状态机）。
禁止编造财报未出现的数字；禁止切块忽略上下文；必须穷举全文中构成「验证→良率/直通→交付」闭环的多处原句。

doc_type: {doc_type}
状态机节点（只能选一）: {nodes}
上期状态（deepsea_indicator_state / T1 快照）: {prior_line}
时序拦截基准 nvidia_blackwell_ga_date: {upstream}
cache_group: {CACHE_GROUP}

概念探针（全文穷举）:
{concept_block}

【全文 Markdown / 公告+业绩会+互动易 拼接】
{full_text[:48000]}

任务：
1. 扫描全文，提取所有关于 GB200/NVL72 客户验证进度、测试损耗、出货节奏的**原文短句**（每条≤512字，带说话人/章节若可识别）。
2. 多点证据拼图：联合多处原句判定 signal_status（不可仅凭单一关键词）。
3. 对比上期状态输出 momentum_delta: accelerating | stalled | reversed | unknown。

输出严格 JSON：
{{
  "signal_status": "RUMOR|EVT|DVT|PVT|MP|UNKNOWN",
  "evidence_quotes": ["原句1", "原句2"],
  "fact_statement": "客观事实句，无买卖建议",
  "momentum_delta": "accelerating|stalled|reversed|unknown",
  "momentum_rationale": "对比上期的边际变化理由",
  "doc_id": "{doc_id}",
  "confidence": "high|medium|low"
}}"""


def _call_with_optional_pro(t0: dict[str, Any], *, prior: str | None, cfg: dict[str, Any]) -> dict[str, Any]:
    prompt = _build_prompt(t0, prior_status=prior, cfg=cfg)
    parsed = call_semantic_json(prompt=prompt, model_tier="flash")
    escalation = str(cfg.get("model_tier_escalation") or "").strip()
    if escalation == "pro_on_low_confidence" and needs_pro_review(parsed):
        logger.info("fii_gb200_milestone Flash 置信不足 · 拉起 Pro 复核")
        pro_parsed = call_semantic_json(prompt=prompt, model_tier="pro")
        pro_parsed["llm_tag"] = "deepseek-pro"
        return pro_parsed
    parsed["llm_tag"] = "deepseek-flash"
    return parsed


def infer_gb200_milestone_semantic(t0: dict[str, Any]) -> dict[str, Any]:
    """DeepSea 语义推理主入口。"""
    text = _combined_text(t0)
    if len(text.strip()) < 20:
        raise ValueError("T0 全文过短，无法语义推演")

    cfg = _probe_routing_config(t0)
    prior = _prior_signal_status(t0)
    try:
        parsed = _call_with_optional_pro(t0, prior=prior, cfg=cfg)
    except Exception as exc:
        logger.warning("fii_gb200_milestone DeepSeek 失败，回退关键词: %s", exc)
        parsed = _rule_fallback_semantic(t0)
        parsed["llm_tag"] = f"rule_fallback:{type(exc).__name__}"

    status = str(parsed.get("signal_status") or "UNKNOWN").strip().upper()
    if status not in _STATE_NODES and status != "UNKNOWN":
        status = "UNKNOWN"

    quotes = parsed.get("evidence_quotes") or []
    if isinstance(quotes, str):
        quotes = [quotes]
    quotes = [str(q).strip()[:512] for q in quotes if str(q).strip()]

    event_date = _parse_event_date(t0)
    paradox = check_temporal_paradox(event_date, upstream_bottleneck_date(), status if status != "UNKNOWN" else None)
    if paradox.get("paradox"):
        status = "UNKNOWN"
        parsed["momentum_delta"] = "reversed"
        parsed["momentum_rationale"] = (
            (parsed.get("momentum_rationale") or "") + " · 时序悖论：事件早于 Blackwell GA 基准。"
        ).strip()

    transition = detect_state_transition(prior, status if status in _STATE_NODES else None)
    stage_label = None
    if status in NPI_STATE_DICTIONARY:
        stage_label = str(NPI_STATE_DICTIONARY[status]["label_zh"])

    shadow = build_shadow_validation(t0, signal_status=status)

    return {
        "probe_key": PROBE_KEY,
        "symbol": str(t0.get("symbol") or "601138"),
        "signal_type": "semantic",
        "batch_id": CACHE_GROUP,
        "cache_group": CACHE_GROUP,
        "signal_status": status,
        "value": None,
        "calculation_logic": None,
        "evidence_quotes": quotes,
        "fact_statement": str(parsed.get("fact_statement") or "").strip() or "语义推演未完成。",
        "momentum_delta": str(parsed.get("momentum_delta") or "unknown"),
        "momentum_rationale": str(parsed.get("momentum_rationale") or ""),
        "shadow_validation": shadow,
        "doc_id": str(parsed.get("doc_id") or t0.get("doc_id") or ""),
        "llm_tag": parsed.get("llm_tag"),
        "confidence": parsed.get("confidence") or "medium",
        "prior_signal_status": prior,
        "state_transition": transition,
        "lifecycle_stage_label": stage_label,
        "temporal_check": paradox,
        "source": "cninfo_announcement_feed · deepsea_semantic",
        "routing": {
            "t1_pipeline": cfg.get("t1_pipeline"),
            "model_tier": cfg.get("model_tier"),
            "model_tier_escalation": cfg.get("model_tier_escalation"),
            "stale_days": cfg.get("stale_days"),
            "cohort_peers": cfg.get("cohort_peers"),
        },
    }


__all__ = [
    "build_shadow_validation",
    "infer_gb200_milestone_semantic",
    "needs_pro_review",
]
