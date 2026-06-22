"""Z0-M0 wind_scan · v5.1 Pure Policy + Z0+ Investment Grade（纯政策风向 + 投资级评分）。

[Ref: 34_ §3.0a · 32_ §2.4.1]
Z0 定位：在国家政策文件中筛选出国家意志推动的方向。
Z0+ 定位：叠加「商业轨迹」和「资本引力」两个投资维度，将排名从「政府最操心」校正为「市场最可能给溢价」。

D1=政策方向（基础分数）· Z0+ = 四轴投资级综合评分 · 前端支持双视角切换
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _parse_float(v, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ═══════════════ P0 快照 ═══════════════

def build_p0_snapshot(metrics: dict[str, Any]) -> dict[str, Any]:
    regime = metrics.get("M.liq.regime_composite") or {}
    pmi = metrics.get("M.macro.pmi") or {}
    rdata = (regime.get("data") or {}) if regime.get("status") == "ok" else {}
    pdata = (pmi.get("data") or {}) if pmi.get("status") == "ok" else {}
    return {
        "liquidity_regime": rdata.get("liquidity_regime", "pending"),
        "macro_regime": rdata.get("macro_regime") or pdata.get("regime", "pending"),
        "pmi": pdata.get("pmi"),
    }


# ═══════════════ 政策方向五级评级（丰富标签+经典案例） ═══════════════

_POLICY_TIER_SPEC: dict[str, Any] = {
    "label": "政策方向",
    "tiers": [
        {"range": (0.80, 1.00), "label": "强驱动", "color": "#16a34a", "css": "bg-green-600 text-white"},
        {"range": (0.60, 0.79), "label": "显著",   "color": "#65a30d", "css": "bg-lime-600 text-white"},
        {"range": (0.40, 0.59), "label": "中等",   "color": "#ca8a04", "css": "bg-yellow-600 text-white"},
        {"range": (0.20, 0.39), "label": "轻度",   "color": "#9ca3af", "css": "bg-gray-400 text-white"},
        {"range": (0.00, 0.19), "label": "缺位",   "color": "#d1d5db", "css": "bg-gray-200 text-gray-500"},
    ],
    "desc": (
        "基于国家政策文件的LLM语义分析：逐篇提取原文行业名称，判断利好/利空方向与影响强度，"
        "经数据源权威权重、实施状态、时间衰减三因子加权后，按方向净值×质量×置信度合成。"
        "综合评分 = f(利好/利空方向净值, 综合质量分, 文档数量置信度) × [高价值政策1.15倍加成]。"
    ),
}

_RICH_TIER_EXPLANATIONS: dict[str, dict[str, str]] = {
    "强驱动": {
        "summary": "该方向是国家中长期战略重点，有多部委协同、专项规划、财政拨款等实质性配套措施。政策确定性极高。",
        "typical_evidence": (
            "国务院/中办国办发文；标题含「规划」「决定」「意见」等正式文件；"
            "正文中明确设定量化目标（如「到2030年产业规模达到XX万亿」）；"
            "配套有财政拨款、税收减免、专项基金、土地/审批绿色通道等实质性措施。"
        ),
        "examples": (
            "《新能源汽车产业发展规划(2021-2035年)》：明确2025年销量占比20%，配套购置税减免+充电桩基建专项拨款\n"
            "十四五规划将「数字经济核心产业增加值占GDP比重提升至10%」列为约束性指标\n"
            "国务院《中国制造2025》将新一代信息技术/高端装备列为十大重点领域，配套国家制造业转型升级基金500亿"
        ),
        "decision_hint": (
            "该方向是国家意志级别的确定性赛道，在Z1阶段应优先筛选此板块内龙头标的做深度基本面分析。"
            "注意：政策强驱动 ≠ 短期股价上涨。政策到业绩兑现通常有1-3年滞后，需结合标的实际经营数据判断。"
        ),
        "icon": "🔥",
    },
    "显著": {
        "summary": "政策明确涉及该赛道，有具体条款或部委级文件支撑。国家层面认可度高，但尚未上升到国家战略核心位。",
        "typical_evidence": (
            "部委级发文（工信部/发改委/科技部等）；正文中有针对该赛道的专门章节/条款；"
            "含「重点支持」「鼓励发展」「加快培育」等明确表述；可能有行业标准制定或试点示范安排。"
        ),
        "examples": (
            "工信部《算力基础设施高质量发展行动计划》：明确到2025年算力规模目标\n"
            "发改委等多部门《氢能产业发展中长期规划》：明确产业阶段目标\n"
            "科技部《新一代人工智能发展规划》：将AI列为核心突破方向，设立国家实验室"
        ),
        "decision_hint": (
            "该方向政策面确定性较高，但需进一步确认是否有「强驱动」级别的升级趋势。"
            "适合放入Z1备选池，优先观察是否出现国务院级别文件将方向升级。"
        ),
        "icon": "📈",
    },
    "中等": {
        "summary": "政策部分涉及或多次顺带提及该方向，有一定关注度但尚未形成系统性政策支撑。",
        "typical_evidence": (
            "政策文件中出现该行业名称，但属于列举/顺带提及/方向性描述；"
            "没有专门章节展开；措施多为「鼓励探索」「研究推进」等软性表述。"
        ),
        "examples": (
            "某国务院文件提到「促进新能源、新材料、高端装备等战略性新兴产业发展」——列举式提及\n"
            "年度政府工作报告中一句话提及「加快数字化发展」——无后续具体措施\n"
            "多部委联合文件中将某行业列入「需要关注的领域」而非「重点扶持领域」"
        ),
        "decision_hint": (
            "该方向目前仅有政策关注度而缺乏执行力，建议保持观察。"
            "关注是否有后续文件将方向从「顺带提及」升级为「专门章节」。"
        ),
        "icon": "👀",
    },
    "轻度": {
        "summary": "政策文件中极少或间接涉及，无实质性扶持措施。多为关联方向被波及。",
        "typical_evidence": (
            "政策正文中极少出现该行业名称，或仅在背景介绍/形势分析中间接关联；"
            "没有针对性的政策条款或措施表述。"
        ),
        "examples": (
            "某文件提及「环保节能」时实际在讲绿色建筑/碳排放，与具体产业扶持无关\n"
            "某文件提及「AI」仅作为技术趋势背景，正文不涉及AI产业政策\n"
            "某消费政策文件提到「数字化消费场景」仅一句话，无后续条款"
        ),
        "decision_hint": (
            "该方向在当前政策周期内缺乏实质支撑，不建议作为Z1主要候选方向。"
            "但如果发现high_value_flag标记，请以上述标记为准重新判断。"
        ),
        "icon": "📋",
    },
    "缺位": {
        "summary": "当前政策文档库中暂无涉及该方向的有效记录。",
        "typical_evidence": "该行业/板块名称未在任何已采集的政策文档中出现。",
        "examples": "该板块仅出现在市场数据中，无政策面数据支撑",
        "decision_hint": "该方向在当前政策周期内无政策面支撑，仅由市场概念/行业数据驱动。不推荐作为政策风口候选。",
        "icon": "—",
    },
}

# 需要高级模型复审的阈值
_REVIEW_THRESHOLD = 0.60


def _classify_policy_tier(score: float | None) -> dict[str, Any] | None:
    """将 D1 分数映射到评级档位（含丰富标签解释）。"""
    if score is None:
        return None
    s = _clamp01(score)
    for t in _POLICY_TIER_SPEC["tiers"]:
        lo, hi = t["range"]
        if lo <= s <= hi:
            label = t["label"]
            rich = _RICH_TIER_EXPLANATIONS.get(label, {})
            return {
                "label": label,
                "color": t["color"],
                "css": t["css"],
                "icon": rich.get("icon", ""),
                "summary": rich.get("summary", ""),
                "typical_evidence": rich.get("typical_evidence", ""),
                "examples": rich.get("examples", ""),
                "decision_hint": rich.get("decision_hint", ""),
            }
    return _classify_policy_tier(0.0)


def get_tier_specs() -> dict[str, Any]:
    """对外暴露完整评级定义（含丰富标签解释）。"""
    return {
        "policy_tier_spec": _POLICY_TIER_SPEC,
        "rich_tier_explanations": _RICH_TIER_EXPLANATIONS,
        "review_threshold": _REVIEW_THRESHOLD,
    }


async def review_high_tier_sector(
    sector: str,
    tier_label: str,
    d1_score: float,
    evidence_docs: list[dict[str, Any]],
    *,
    model: str = "claude-opus-4-20250514",
) -> dict[str, Any]:
    """用更强模型复审高评级板块（D1≥0.6），防止误判。

    将板块的政策证据链发送给高级模型（Claude Opus/DeepSeek-R1），
    由模型确认或调整评级。仅当 wind_scan 产出「显著」或「强驱动」时调用。
    """
    if evidence_docs:
        evidence_text = "\n\n---\n\n".join(
            f"文档标题: {d.get('title', '')}\n"
            f"方向: {d.get('direction', '')}\n"
            f"原文引用: {'；'.join(d.get('evidence_quotes', [])[:3])}\n"
            f"推理: {d.get('reasoning', '')}"
            for d in evidence_docs[:10]
        )
    else:
        evidence_text = "（无详细证据文档）"

    review_prompt = f"""你是一位投研政策审计审核专家。系统已将以下行业板块评为「{tier_label}」（得分 {d1_score:.0f}/100）。

请审核证据链，判断这个评级是否合理，是否存在误判。

【板块名称】{sector}
【当前评级】{tier_label}
【政策得分】{d1_score:.2f}

【证据链】
{evidence_text}

请输出JSON：
{{
  "confirm": true/false,
  "adjusted_tier": "显著|中等|轻度|缺位",
  "adjusted_score": 0.XX,
  "reasoning": "审核判断依据（中文，≤200字）",
  "key_evidence_quote": "最具说服力的一条原文引用",
  "risk_factors": ["可能的风险点"]
}}"""

    try:
        from apps.common.ai_dispatcher import AIDispatcher
        dispatcher = AIDispatcher.default()
        result = dispatcher.call(
            scene="review_policy_tier",
            messages=[
                {"role": "system", "content": "你是投研政策审计审核专家，输出严格JSON。"},
                {"role": "user", "content": review_prompt},
            ],
            temperature=0.0,
            max_tokens=1500,
            model_override=model,
            force_route="anthropic",
        )
        import json, re
        raw = result.text or ""
        clean = raw.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```(?:json)?\s*", "", clean)
            clean = re.sub(r"\s*```$", "", clean)
        review = json.loads(clean)
        return {
            "reviewed": True,
            "model": model,
            "confirm": bool(review.get("confirm", True)),
            "adjusted_tier": review.get("adjusted_tier") if not review.get("confirm") else tier_label,
            "adjusted_score": review.get("adjusted_score") if not review.get("confirm") else d1_score,
            "reasoning": str(review.get("reasoning", ""))[:200],
            "key_evidence_quote": str(review.get("key_evidence_quote", ""))[:300],
            "risk_factors": review.get("risk_factors", [])[:3],
        }
    except Exception as exc:
        logger.warning("复审失败 sector=%s: %s", sector, exc)
        return {"reviewed": False, "error": str(exc)[:200]}


# ═══════════════ 数据合并（仅保留政策入口） ═══════════════

def _merge_sector_inputs(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    """v5.0 Pure Policy：仅合并政策数据。"""
    merged: dict[str, dict[str, Any]] = {}

    policy = metrics.get("M.sector.policy_direction") or {}
    if policy.get("status") != "ok":
        return []

    pdata = policy.get("data") or {}
    for item in pdata.get("top_sectors") or []:
        sector = str(item.get("sector", "")).strip()
        if not sector:
            continue
        raw_score = float(item.get("policy_score", 0))
        high_val = bool(item.get("high_value_flag"))
        merged[sector] = {
            "sector": sector,
            "sector_type": item.get("sector_type", "canonical"),
            "policy_score": raw_score,
            "high_value_flag": high_val,
            "hit_count": int(item.get("hit_count", 0)),
            "direction": item.get("direction") or item.get("consensus_direction"),
            "sub_concepts": item.get("sub_concepts") or [],  # v2.1
            # v3.0 Z0+: 投资级评分字段
            "dominant_revenue_model": str(item.get("dominant_revenue_model", "political_rhetoric")),
            "dominant_narrative_type": str(item.get("dominant_narrative_type", "political_slogan")),
            "dominant_policy_phase": str(item.get("dominant_policy_phase", "maturation")),
            "regime_change_doc_count": int(item.get("regime_change_doc_count") or 0),
            "policy_acceleration": float(item.get("policy_acceleration") or 1.0),
            "best_imp_strength": str(item.get("best_imp_strength", "light")),
            "avg_toolkit": item.get("avg_toolkit") or {},
        }

    return list(merged.values())


# ═══════════════ D1 主评分 ═══════════════

def _d1_policy_score(td: dict[str, Any] | None, high_value_flag: bool) -> float | None:
    """纯政策方向评分（0-1）+ 落地力度多级加权。

    落地力度系数来自 LLM 识别的 implementation_strength（替代旧 high_value_flag 1.15x）：
    comprehensive(1.30) > targeted(1.20) > moderate(1.10) > light(1.00) > symbolic(0.85)
    """
    if not td:
        return None
    net_dir = float(td.get("net_direction", 0))
    quality = float(td.get("quality", 0))
    confidence = float(td.get("confidence", 0))
    if net_dir > 0:
        d1 = net_dir * quality * (0.3 + 0.7 * confidence)
    else:
        d1 = net_dir * quality * 0.2
    # 落地力度多级系数（v5.1 · 替代旧 high_value_flag 1.15x）
    imp_mult = float(td.get("imp_force_multiplier", 1.0))
    d1 = d1 * imp_mult
    return round(_clamp01(d1), 4)


# ═══════════════ 主合成入口 ═══════════════

def synthesize_wind_scan(metrics: dict[str, Any], *, top_n: int = 30) -> dict[str, Any]:
    """v5.0 Pure Policy：Z0 仅做政策风向筛选。D1=政策方向（100%权重）。"""
    p0 = build_p0_snapshot(metrics)

    sector_inputs = _merge_sector_inputs(metrics)
    if not sector_inputs:
        pol_st = (metrics.get("M.sector.policy_direction") or {}).get("status")
        return {
            "status": "empty",
            "blocker": f"无政策赛道产出（policy={pol_st}）",
            "p0_snapshot": p0,
            "candidates": [],
            "advisory_only": True,
        }

    from apps.copilot.services.deepsea.policy_reader import compute_time_weighted_directions
    temporal = compute_time_weighted_directions() if sector_inputs else {}

    candidates: list[dict[str, Any]] = []
    for s in sector_inputs:
        sn = str(s.get("sector", "")).strip()
        td = temporal.get(sn)
        high_value_flag = bool(s.get("high_value_flag"))

        d1 = _d1_policy_score(td, high_value_flag)
        tier = _classify_policy_tier(d1) if d1 is not None else None
        needs_review = d1 is not None and d1 >= _REVIEW_THRESHOLD and tier is not None

        # v3.0 Z0+: 投资级评分（仅对规范赛道计算）
        z0_plus_score: float | None = None
        z0_plus_breakdown: dict[str, Any] | None = None
        if s.get("sector_type") == "canonical":
            from apps.copilot.metrics.synthesizer.investment_scorer import score_investment_grade
            b2_agg = {
                "composite_score": float(td.get("net_direction", 0)) if td else 0,
                "policy_acceleration": float(s.get("policy_acceleration", 1.0)),
                "regime_change_doc_count": int(s.get("regime_change_doc_count", 0)),
                "dominant_policy_phase": str(s.get("dominant_policy_phase", "maturation")),
                "dominant_revenue_model": str(s.get("dominant_revenue_model", "political_rhetoric")),
                "dominant_narrative_type": str(s.get("dominant_narrative_type", "political_slogan")),
                "best_imp_strength": str(s.get("best_imp_strength", "light")),
                "avg_toolkit": s.get("avg_toolkit") or {},
            }
            result = score_investment_grade(sn, b2_agg)
            z0_plus_score = result["z0_plus_score"]
            z0_plus_breakdown = result["breakdown"]

        candidates.append({
            "sector": sn,
            "sector_type": s.get("sector_type", "canonical"),
            "d1_score": d1,
            "d1_tier": tier,
            "z0_plus_score": z0_plus_score,        # v3.0 新增
            "z0_plus_breakdown": z0_plus_breakdown,  # v3.0 新增
            "high_value_flag": high_value_flag,
            "needs_review": needs_review,
            "review_status": "pending" if needs_review else None,
            "sub_concepts": s.get("sub_concepts") or [],  # v2.1：A股概念板
            "d1_detail": {
                "net_direction": round(float(td.get("net_direction", 0)), 4) if td else None,
                "quality": round(float(td.get("quality", 0)), 4) if td else None,
                "confidence": round(float(td.get("confidence", 0)), 4) if td else None,
                "doc_count": int(td.get("doc_count", 0)) if td else 0,
                "tailwind_count": int(td.get("tailwind_count", 0)) if td else 0,
                "headwind_count": int(td.get("headwind_count", 0)) if td else 0,
                "imp_force_multiplier": float(td.get("imp_force_multiplier", 1.0)) if td else 1.0,
                "imp_force_label": str(td.get("imp_force_label", "方向性鼓励")) if td else "方向性鼓励",
                "imp_strength": str(td.get("imp_strength", "light")) if td else "light",
                "implementation_bonus": td.get("implementation_bonus", 0) if td else 0,
                "toolkit_total": td.get("toolkit_total", 0) if td else 0,
                "avg_toolkit": td.get("avg_toolkit", {}) if td else {},
            } if td else None,
            "evidence_summary": (
                f"政策文档命中 {s.get('hit_count', 0)} 次 · 方向 {s.get('direction', 'neutral')}"
            ),
        })

    # D1 排序（政策视角）
    candidates.sort(key=lambda x: (x["d1_score"] is not None, x["d1_score"] or 0), reverse=True)
    candidates = candidates[:top_n]
    for i, c in enumerate(candidates, start=1):
        c["rank"] = i

    return {
        "status": "ready",
        "blocker": None,
        "p0_snapshot": p0,
        "candidates": candidates,
        "advisory_only": True,
        "mode": "policy_investment_v5.1",
        "available_views": ["policy", "investment"],  # v3.0 双视角支持
        "review_threshold": _REVIEW_THRESHOLD,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


__all__ = [
    "synthesize_wind_scan",
    "get_tier_specs",
    "review_high_tier_sector",
    "build_p0_snapshot",
    "_classify_policy_tier",
    "_REVIEW_THRESHOLD",
    "_RICH_TIER_EXPLANATIONS",
    "_POLICY_TIER_SPEC",
]
