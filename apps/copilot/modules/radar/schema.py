"""模式 C 深度研报 · 9 维结构化契约（T2 Opus 输出 schema + prompt + 解析 + 成本）。

自给式 Opus 深度研报：T0 akshare 直采 → T1 压缩事实矩阵 → T2 Opus 9 维结构化推理。
**no-mock**：硬失败显式 status=error，绝不伪造 pending；**no-auto-execute**：全 advisory。

[Ref: step_14 §3 · 25_ §2 统一三段流水线]
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

# ── 9 维定义（key, 中文标签, emoji, 一句说明）────────────────────────────────
DIMENSIONS: list[dict[str, str]] = [
    {"key": "niche", "label": "生态位", "emoji": "🧬",
     "hint": "公司在产业中的独特定位与不可替代性"},
    {"key": "value_chain", "label": "价值链位置", "emoji": "🔗",
     "hint": "处于上游/中游/下游，议价能力与利润分配"},
    {"key": "is_leader", "label": "龙头地位", "emoji": "👑",
     "hint": "是否细分龙头：yes / no / inferred"},
    {"key": "moat", "label": "护城河壁垒", "emoji": "🧱",
     "hint": "技术/品牌/成本/网络/牌照等壁垒强度"},
    {"key": "profit_quality", "label": "利润质量", "emoji": "💰",
     "hint": "盈利的真实性、可持续性、现金含量"},
    {"key": "market_phase", "label": "市场阶段", "emoji": "🌡️",
     "hint": "炒概念 concept / 炒预期 expectation / 炒业绩 realization / 利好出尽 exhaustion"},
    {"key": "catalyst_timeline", "label": "利好时间线", "emoji": "📅",
     "hint": "未来催化事件及其时间窗、概率（推演非承诺）"},
    {"key": "risk", "label": "风险", "emoji": "⚠️",
     "hint": "基本面/估值/政策/流动性等主要风险"},
    {"key": "valuation", "label": "估值（戴维斯双击）", "emoji": "📊",
     "hint": "PE/PB 分位、戴维斯双击/双杀可能性"},
]

DIM_KEYS = [d["key"] for d in DIMENSIONS]
DIM_META = {d["key"]: d for d in DIMENSIONS}

MARKET_PHASE_LABELS = {
    "concept": "炒概念",
    "expectation": "炒预期",
    "realization": "炒业绩",
    "exhaustion": "利好出尽",
}

# ── 成本（Opus 定价，可由 env 覆盖）──────────────────────────────────────────
# 默认按 Opus：input $15/MTok、output $75/MTok，USD→CNY≈7.2
_USD_CNY = float(os.getenv("RADAR_USD_CNY", "7.2"))
_OPUS_IN_USD_PER_MTOK = float(os.getenv("RADAR_OPUS_IN_USD_PER_MTOK", "15"))
_OPUS_OUT_USD_PER_MTOK = float(os.getenv("RADAR_OPUS_OUT_USD_PER_MTOK", "75"))


def estimate_cost_yuan(tokens_in: int, tokens_out: int) -> float:
    """按真实 token 数估算本次 Opus 调用成本（元）。"""
    cost = (
        (tokens_in or 0) / 1_000_000 * _OPUS_IN_USD_PER_MTOK
        + (tokens_out or 0) / 1_000_000 * _OPUS_OUT_USD_PER_MTOK
    ) * _USD_CNY
    return round(cost, 4)


# ── Prompt 构建 ──────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = (
    "你是一名严谨的 A 股深度研究分析师，对标巴菲特式基本面+产业链穿透。"
    "你将收到一份由真实数据（行情/公司资料/财务摘要/估值分位）压缩成的事实矩阵，"
    "请基于这些事实做 9 个维度的深度推理，每个维度给出：明确结论(verdict)、"
    "推理过程(reasoning，结合矩阵中的真实数字)、证据(evidence，引用矩阵字段或数值)、"
    "置信度(confidence，0~1，事实不足时调低而非编造)。"
    "**严禁编造矩阵中没有的数字**；事实不足时在 reasoning 中说明并降低 confidence。"
    "全部为研究 advisory，不构成交易指令。只输出 JSON，不要任何额外文字。"
)

_SCHEMA_HINT = """输出严格如下 JSON 结构（不要 markdown 代码块）：
{
  "overall": {"conclusion": "一句话总结", "action_advisory": "观察/研究 advisory（非交易指令）", "confidence": 0.0},
  "dimensions": {
    "niche":            {"verdict": "", "reasoning": "", "evidence": [], "confidence": 0.0},
    "value_chain":      {"verdict": "上游|中游|下游|平台", "reasoning": "", "evidence": [], "confidence": 0.0},
    "is_leader":        {"verdict": "yes|no|inferred", "reasoning": "", "evidence": [], "confidence": 0.0},
    "moat":             {"verdict": "强|中|弱", "reasoning": "", "evidence": [], "confidence": 0.0},
    "profit_quality":   {"verdict": "高|中|低", "reasoning": "", "evidence": [], "confidence": 0.0},
    "market_phase":     {"verdict": "concept|expectation|realization|exhaustion", "reasoning": "", "evidence": [], "confidence": 0.0},
    "catalyst_timeline":{"verdict": "", "items": [{"window": "如 1-2 季度", "event": "", "probability": "高|中|低"}], "reasoning": "", "evidence": [], "confidence": 0.0},
    "risk":             {"verdict": "", "reasoning": "", "evidence": [], "confidence": 0.0},
    "valuation":        {"verdict": "低估|合理|高估", "davis_double": "双击可能|中性|双杀风险", "pe_percentile": null, "reasoning": "", "evidence": [], "confidence": 0.0}
  }
}"""


def build_opus_messages(symbol: str, name: str, matrix: dict[str, Any]) -> list[dict[str, str]]:
    """构建喂给 Opus 的 messages（system + user 含事实矩阵 + schema 约束）。"""
    facts = json.dumps(
        {"symbol": symbol, "name": name, "fact_matrix": matrix.get("matrix") or matrix},
        ensure_ascii=False,
        indent=1,
    )
    user = f"【标的】{name}（{symbol}）\n【事实矩阵】\n{facts}\n\n{_SCHEMA_HINT}"
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


# ── 解析 Opus 输出 ────────────────────────────────────────────────────────────
def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    # 直接解析；失败则截取首个 { 到末个 }
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        l, r = text.find("{"), text.rfind("}")
        if l >= 0 and r > l:
            return json.loads(text[l : r + 1])
        raise


def parse_opus_verdict(text: str) -> dict[str, Any]:
    """把 Opus 原文解析为规范化 9 维结构；缺维补 status 标注而非编造内容。"""
    parsed = _extract_json(text)
    dims_in = parsed.get("dimensions") or {}
    dims_out: dict[str, Any] = {}
    for key in DIM_KEYS:
        d = dims_in.get(key) or {}
        norm = {
            "verdict": d.get("verdict") or "—",
            "reasoning": d.get("reasoning") or "",
            "evidence": d.get("evidence") if isinstance(d.get("evidence"), list) else [],
            "confidence": _safe_float(d.get("confidence"), 0.0),
        }
        if key == "catalyst_timeline":
            norm["items"] = d.get("items") if isinstance(d.get("items"), list) else []
        if key == "valuation":
            norm["davis_double"] = d.get("davis_double") or "—"
            norm["pe_percentile"] = d.get("pe_percentile")
        if not d:
            norm["status"] = "missing"  # Opus 未给该维（非伪造）
        dims_out[key] = norm

    overall = parsed.get("overall") or {}
    return {
        "overall": {
            "conclusion": overall.get("conclusion") or "—",
            "action_advisory": overall.get("action_advisory") or "—",
            "confidence": _safe_float(overall.get("confidence"), 0.0),
        },
        "dimensions": dims_out,
    }


def _safe_float(v: Any, default: float) -> float:
    try:
        f = float(v)
        return max(0.0, min(1.0, f))
    except (TypeError, ValueError):
        return default
