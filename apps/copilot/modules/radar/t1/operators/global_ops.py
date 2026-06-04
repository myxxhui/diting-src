"""T1 算子 op_t01~op_t03。

[Ref: 27_ §3.2]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.radar.t1.operators.types import OpResult, node


def op_t01_market_temperature(t0_raw: dict[str, Any]) -> OpResult:
    macro = t0_raw.get("macro") or {}
    ms = macro.get("market_sentiment") or {}
    if ms.get("status") != "ok":
        return OpResult("global_and_meso", "market_temperature", None, "缺少 T0-1 全市场情绪数据")
    adv = ms.get("advance_ratio")
    turnover = ms.get("turnover_vs_prev_pct")
    tag = "缩量退潮" if turnover is not None and turnover < -5 else "市场偏冷"
    if adv is not None and adv >= 0.5:
        tag = "情绪回暖"
    if adv is not None and adv < 0.3:
        tag = "冰点弱势"
    ctx = f"上涨占比 {adv} · 成交额 {ms.get('total_turnover_yi')} 亿"
    return OpResult("global_and_meso", "market_temperature", node(turnover or adv, tag, ctx))


def op_t02_sector_momentum(t0_raw: dict[str, Any]) -> OpResult:
    sm = (t0_raw.get("macro") or {}).get("sector_momentum") or {}
    if sm.get("status") != "ok":
        return OpResult("global_and_meso", "sector_momentum", None, "缺少 T0-2 板块动能")
    pct = sm.get("pct_chg_3d")
    tag = "板块领涨" if pct is not None and pct >= 3 else "板块中性"
    if pct is not None and pct <= -3:
        tag = "板块退潮"
    return OpResult(
        "global_and_meso",
        "sector_momentum",
        node(pct, tag, f"行业 {sm.get('industry')} 近3日涨跌 {pct}%"),
    )


def op_t03_sector_flow(t0_raw: dict[str, Any]) -> OpResult:
    sf = (t0_raw.get("macro") or {}).get("sector_flow") or {}
    if sf.get("status") != "ok":
        return OpResult("global_and_meso", "sector_flow", None, "缺少 T0-3 板块资金")
    net = sf.get("net_inflow_5d_yi")
    tag = "主力净流入" if net is not None and net > 0 else "主力净流出"
    return OpResult(
        "global_and_meso",
        "sector_flow",
        node(net, tag, f"板块 5 日主力净流入 {net} 亿元"),
    )
