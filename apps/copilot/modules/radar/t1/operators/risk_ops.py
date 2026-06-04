"""T1 算子 op_t14~op_t17。

[Ref: 27_ §3.6]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.radar.t1.operators.types import OpResult, node


def op_t14_financial_red(t0_raw: dict[str, Any]) -> OpResult:
    fin = (t0_raw.get("risk") or {}).get("financial_slice") or t0_raw.get("financials") or {}
    if fin.get("status") != "ok":
        return OpResult("risks_red_flags", "financial_quality", None, "缺少 T0-14 财务切片")
    ocf = fin.get("operating_cashflow")
    profit = fin.get("net_profit_parent") or fin.get("net_profit")
    tag = "财务摘要就绪"
    val = fin.get("roe")
    if ocf is not None and profit is not None and ocf < 0 and profit > 0:
        tag = "🔴现金流背离"
        val = ocf
    return OpResult(
        "risks_red_flags",
        "financial_quality",
        node(val, tag, f"ROE {fin.get('roe')}% · 经营现金流 {ocf}"),
    )


def op_t15_pledge(t0_raw: dict[str, Any]) -> OpResult:
    pl = (t0_raw.get("risk") or {}).get("pledge") or {}
    if pl.get("status") != "ok":
        return OpResult("risks_red_flags", "equity_pledge", None, "缺少 T0-15 质押数据")
    ratio = pl.get("pledge_ratio_pct")
    tag = "质押可控"
    if ratio is not None and ratio > 70:
        tag = "🔴极高爆仓风险"
    elif ratio is not None and ratio > 50:
        tag = "质押偏高"
    return OpResult(
        "risks_red_flags",
        "equity_pledge",
        node(ratio, tag, f"大股东质押率 {ratio}%"),
    )


def op_t16_unlock(t0_raw: dict[str, Any]) -> OpResult:
    ul = (t0_raw.get("risk") or {}).get("unlock_schedule") or {}
    if ul.get("status") != "ok":
        return OpResult("risks_red_flags", "share_unlock", None, "缺少 T0-16 解禁计划")
    events = ul.get("events") or []
    first = events[0] if events else {}
    ratio = first.get("ratio_pct")
    tag = "解禁压力可控"
    try:
        r = float(str(ratio).replace("%", ""))
        if r > 5:
            tag = "🔴即期巨额解禁"
    except (TypeError, ValueError):
        r = ratio
    return OpResult(
        "risks_red_flags",
        "share_unlock",
        node(r, tag, f"最近解禁 {first.get('date')} · 占比 {ratio}"),
    )


def op_t17_regulatory_llm(t0_raw: dict[str, Any]) -> OpResult:
    """DeepSeek 槽位 · 须 LLM 分级；无 llm_tag 则 unavailable。"""
    reg = (t0_raw.get("risk") or {}).get("regulatory_events") or {}
    if reg.get("status") != "ok":
        return OpResult("risks_red_flags", "regulatory", None, "缺少 T0-17 监管公告")
    if not reg.get("llm_tag"):
        return OpResult(
            "risks_red_flags",
            "regulatory",
            None,
            "T0-17 DeepSeek 监管分级未执行（须 vLLM/DeepSeek 写入 regulatory_events.llm_tag）",
        )
    return OpResult(
        "risks_red_flags",
        "regulatory",
        node(None, str(reg["llm_tag"]), (reg.get("raw_text") or "")[:200]),
    )
