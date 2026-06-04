"""T0-8~11 微观算子。

[Ref: 27_ §3.4]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.radar.t1.operators.types import OpResult, node


def op_t08_price_action(t0_raw: dict[str, Any], micro: dict[str, Any] | None = None) -> OpResult:
    micro = micro if micro is not None else (t0_raw.get("micro") or {})
    bars = micro.get("bars_250d") or {}
    if bars.get("status") == "ok":
        summary = bars.get("summary") or {}
        limit = int(summary.get("limit_up_count_20d") or 0)
        side = str(summary.get("side_tag") or "横盘")
        tag = side
        if limit >= 3:
            tag = "右侧极度活跃"
        above = summary.get("above_ma20")
        ma20 = summary.get("ma20")
        ctx = (
            f"250日K共{bars.get('bars_count')}根 · "
            f"收盘{'站上' if above else '低于'}MA20({ma20}) · "
            f"近20日涨停{limit}次"
        )
        return OpResult("microstructure", "price_action", node(limit, tag, ctx))

    quote = t0_raw.get("quote") or {}
    if quote.get("status") == "ok":
        pct = quote.get("pct_chg_20d")
        return OpResult(
            "microstructure",
            "price_action",
            None,
            f"缺少 T0-8 250日K · 60日K不可替代（近20日 {pct}%）",
        )
    detail = bars.get("detail") or "250日K线不可用"
    return OpResult("microstructure", "price_action", None, f"缺少 T0-8 量价数据: {detail}")


def op_t09_northbound(t0_raw: dict[str, Any], micro: dict[str, Any] | None = None) -> OpResult:
    micro = micro if micro is not None else (t0_raw.get("micro") or {})
    nb = micro.get("northbound") or {}
    if nb.get("status") == "skip":
        return OpResult("microstructure", "northbound_flow", None, "标的非陆股通成分股，缺少 T0-9 聪明资金数据")
    if nb.get("status") != "ok":
        return OpResult("microstructure", "northbound_flow", None, f"缺少 T0-9 北向数据: {nb.get('detail', '未知')}")

    net5 = nb.get("net_buy_5d_yi")
    net30 = nb.get("net_buy_30d_yi")
    if net5 is not None and net5 > 0:
        tag = "外资持续加仓"
    elif net5 is not None and net5 < 0:
        tag = "外资持续减仓"
    else:
        tag = "北向中性"
    ctx = f"北向近5日净买入 {net5} 亿元 · 近30日 {net30} 亿元"
    return OpResult("microstructure", "northbound_flow", node(net5, tag, ctx))


def op_t10_margin_roc(t0_raw: dict[str, Any], micro: dict[str, Any] | None = None) -> OpResult:
    micro = micro if micro is not None else (t0_raw.get("micro") or {})
    margin = micro.get("margin") or {}
    if margin.get("status") == "skip":
        return OpResult("microstructure", "margin_leverage", None, "标的无融资融券日表披露")
    if margin.get("status") != "ok":
        return OpResult("microstructure", "margin_leverage", None, f"缺少 T0-10 融资数据: {margin.get('detail', '未知')}")

    roc = margin.get("roc_5d")
    nb = micro.get("northbound") or {}
    net5 = nb.get("net_buy_5d_yi") if nb.get("status") == "ok" else None

    tag = "杠杆平稳"
    if roc is not None and roc > 0.05:
        tag = "杠杆做多高涨"
        if net5 is not None and net5 < 0:
            tag = "内资加杠杆游资博弈"
    elif roc is not None and roc < -0.05:
        tag = "杠杆回落"

    pct = round(float(roc) * 100, 2) if roc is not None else None
    ctx = f"融资余额较5日前变化 {pct}% · 最新 {margin.get('latest_date')}"
    return OpResult("microstructure", "margin_leverage", node(roc, tag, ctx))


def op_t11_dragon_tiger(t0_raw: dict[str, Any], micro: dict[str, Any] | None = None) -> OpResult:
    micro = micro if micro is not None else (t0_raw.get("micro") or {})
    dt = micro.get("dragon_tiger") or {}
    if dt.get("status") == "skip":
        return OpResult("microstructure", "dragon_tiger", None, "近10日无龙虎榜上榜记录")
    if dt.get("status") != "ok":
        return OpResult("microstructure", "dragon_tiger", None, f"缺少 T0-11 龙虎榜: {dt.get('detail', '未知')}")

    count = int(dt.get("appearance_count") or 0)
    inst = float(dt.get("institution_net") or 0)
    hot = float(dt.get("hot_money_net") or 0)

    if inst > 0 and hot > 0:
        tag = "机构游资共振"
    elif inst > 0:
        tag = "机构主导"
    elif hot > 0:
        tag = "游资活跃"
    elif count >= 2:
        tag = "频繁上榜"
    else:
        tag = "龙虎榜偶发"

    ctx = f"近10日上榜{count}次 · 机构净额 {inst:.0f} · 知名游资净额 {hot:.0f}"
    return OpResult("microstructure", "dragon_tiger", node(count, tag, ctx))
