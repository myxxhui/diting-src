"""T1 指标节点 · Opus 名牌 + 前端 raw_metrics 抽屉。

[Ref: 28_ §4.1 · 探针节点降噪/分层]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.executing.probe_labels import probe_indicator_name

SOURCE_INTRADAY_TICK = "Redis In-Memory Cache (Intraday Tick)"
SOURCE_PG_EOD = "PG executing_daily_bars · tencent_fqkline"


def _round2(v: float | int | None) -> float | None:
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _qmt_fact_statement(
    *,
    current: float,
    peak: float,
    value: float,
    intraday: bool,
) -> str:
    """纯客观陈述 · 不含定性/界碑结论（界碑由 T2 Opus 推断）。"""
    if intraday:
        return (
            f"盘中快照现价为 {current:.2f}，"
            f"较持仓期绝对峰值 {peak:.2f} 回撤 {value:.2f} 倍 ATR。"
        )
    return (
        f"收盘价为 {current:.2f}，"
        f"较持仓期绝对峰值 {peak:.2f} 回撤 {value:.2f} 倍 ATR。"
    )


def _resolve_source(payload: dict[str, Any], *, intraday: bool) -> str:
    if intraday:
        return SOURCE_INTRADAY_TICK
    return str(payload.get("source") or SOURCE_PG_EOD)


def build_qmt_atr_trailing_node(payload: dict[str, Any]) -> dict[str, Any]:
    """算子 payload → portfolio_signals 指标节点（不含 as_of/entry_date_used）。"""
    peak = _round2(payload.get("peak_price"))
    cur = _round2(payload.get("current"))
    atr = _round2(payload.get("atr20"))
    raw_val = payload.get("value", payload.get("atr_multiple"))
    value = _round2(raw_val)
    if value is None or cur is None or peak is None:
        raise ValueError("qmt_atr_trailing value/peak/current 缺失")

    intraday = bool(payload.get("intraday"))
    if atr is not None and atr > 0:
        logic = f"({peak:.2f} - {cur:.2f}) / {atr:.2f} = {value:.2f}"
    else:
        logic = str(payload.get("calculation_logic") or "")

    fact = _qmt_fact_statement(current=cur, peak=peak, value=value, intraday=intraday)
    raw_metrics: dict[str, Any] = {}
    if atr is not None:
        raw_metrics["atr_20"] = atr
    raw_metrics["peak_price"] = peak
    raw_metrics["current_price"] = cur
    tick = payload.get("last_tick_time")
    if intraday and tick:
        raw_metrics["last_tick_time"] = str(tick)
    elif not intraday:
        as_of = payload.get("as_of")
        if as_of:
            raw_metrics["bar_as_of"] = str(as_of)[:10]

    return {
        "indicator_name": probe_indicator_name("qmt_atr_trailing"),
        "value": value,
        "fact_statement": fact,
        "calculation_logic": logic,
        "source": _resolve_source(payload, intraday=intraday),
        "raw_metrics": raw_metrics,
    }


def build_volume_price_div_node(payload: dict[str, Any]) -> dict[str, Any]:
    """#16 量价背离 · 可溯源分子分母 + 高位空间坐标。"""
    value = _round2(payload.get("value"))
    if value is None:
        raise ValueError("volume_price_div value 缺失")

    raw_metrics: dict[str, Any] = {
        "high_zone_down_vol": _round2(payload.get("high_zone_down_vol")),
        "high_zone_up_vol": _round2(payload.get("high_zone_up_vol")),
        "high_zone_threshold_price": _round2(payload.get("high_zone_threshold_price")),
        "period_max": _round2(payload.get("period_max")),
        "period_min": _round2(payload.get("period_min")),
        "global_vol_ratio": payload.get("global_vol_ratio"),
        "global_up_vol": _round2(payload.get("global_up_vol")),
        "global_down_vol": _round2(payload.get("global_down_vol")),
        "last_bar_datetime": str(payload.get("last_bar_datetime") or ""),
    }
    raw_metrics = {k: v for k, v in raw_metrics.items() if v is not None and v != ""}

    return {
        "indicator_name": probe_indicator_name("volume_price_div"),
        "value": value,
        "fact_statement": str(payload.get("fact_statement") or ""),
        "calculation_logic": str(payload.get("calculation_logic") or ""),
        "source": str(payload.get("source") or ""),
        "raw_metrics": raw_metrics,
    }


def build_smart_money_flow_node(metrics: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    """#17 L2 主力大单 · T1 白盒节点（value 保留 2 位小数）。"""
    value = metrics.get("value_pct")
    if value is None:
        raise ValueError("smart_money_flow value_pct 缺失")
    value_f = round(float(value), 2)
    raw_metrics = dict(metrics.get("raw_metrics") or {})
    src = source or str(metrics.get("source") or "Tushare API (moneyflow)")
    return {
        "indicator_name": probe_indicator_name("smart_money_flow"),
        "value": value_f,
        "fact_statement": str(metrics.get("fact_statement") or ""),
        "calculation_logic": str(metrics.get("calculation_logic") or ""),
        "source": src,
        "raw_metrics": raw_metrics,
    }


def build_level2_super_order_node(metrics: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    """#18 L2 特大单 · 120 日历史分位白盒节点。"""
    value = metrics.get("value")
    if value is None:
        raise ValueError("level2_super_order value 缺失")
    value_f = round(float(value), 2)
    raw_metrics = dict(metrics.get("raw_metrics") or {})
    src = source or str(metrics.get("source") or "Tushare L2 Moneyflow (elg_amount)")
    return {
        "indicator_name": probe_indicator_name("level2_super_order"),
        "value": value_f,
        "fact_statement": str(metrics.get("fact_statement") or ""),
        "calculation_logic": str(metrics.get("calculation_logic") or ""),
        "source": src,
        "raw_metrics": raw_metrics,
    }


def build_margin_short_skew_node(metrics: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    """#19 两融杠杆倾斜度 · 250 日历史分位白盒节点。"""
    value = metrics.get("value")
    if value is None:
        raise ValueError("margin_short_skew value 缺失")
    value_f = round(float(value), 2)
    raw_metrics = dict(metrics.get("raw_metrics") or {})
    src = source or str(metrics.get("source") or "Tushare Margin Detail (T+1 Lag)")
    return {
        "indicator_name": probe_indicator_name("margin_short_skew"),
        "value": value_f,
        "fact_statement": str(metrics.get("fact_statement") or ""),
        "calculation_logic": str(metrics.get("calculation_logic") or ""),
        "source": src,
        "raw_metrics": raw_metrics,
    }


def build_turnover_acceleration_node(metrics: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    """#20 自由换手率异动倍数白盒节点。"""
    value = metrics.get("value")
    if value is None:
        raise ValueError("turnover_acceleration value 缺失")
    value_f = round(float(value), 2)
    raw_metrics = dict(metrics.get("raw_metrics") or {})
    src = source or str(metrics.get("source") or "Tushare Daily Basic (turnover_rate_f)")
    return {
        "indicator_name": probe_indicator_name("turnover_acceleration"),
        "value": value_f,
        "fact_statement": str(metrics.get("fact_statement") or ""),
        "calculation_logic": str(metrics.get("calculation_logic") or ""),
        "source": src,
        "raw_metrics": raw_metrics,
    }


def build_block_trade_discount_node(metrics: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    """#21 大宗交易加权折价与盘口冲击白盒节点。"""
    value = metrics.get("value")
    if value is None:
        raise ValueError("block_trade_discount value 缺失")
    value_f = round(float(value), 2)
    raw_metrics = dict(metrics.get("raw_metrics") or {})
    src = source or str(metrics.get("source") or "Tushare Block Trade (VWAP Aggregated)")
    return {
        "indicator_name": probe_indicator_name("block_trade_discount"),
        "value": value_f,
        "fact_statement": str(metrics.get("fact_statement") or ""),
        "calculation_logic": str(metrics.get("calculation_logic") or ""),
        "source": src,
        "raw_metrics": raw_metrics,
    }


def build_retail_concentration_node(metrics: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    """#22 户均持股集中度白盒节点。"""
    value = metrics.get("value")
    if value is None:
        raise ValueError("retail_concentration value 缺失")
    value_f = round(float(value), 2)
    raw_metrics = dict(metrics.get("raw_metrics") or {})
    src = source or str(metrics.get("source") or "AkShare Interactive Platform Scraper (Event-Driven)")
    return {
        "indicator_name": probe_indicator_name("retail_concentration"),
        "value": value_f,
        "fact_statement": str(metrics.get("fact_statement") or ""),
        "calculation_logic": str(metrics.get("calculation_logic") or ""),
        "source": src,
        "raw_metrics": raw_metrics,
    }


def build_insider_sell_actual_node(metrics: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    """#23 内部人90日净减持当量白盒节点。"""
    value = metrics.get("value")
    if value is None:
        raise ValueError("insider_sell_actual value 缺失")
    value_f = round(float(value), 2)
    raw_metrics = dict(metrics.get("raw_metrics") or {})
    src = source or str(metrics.get("source") or "Tushare Pro (stk_holdertrade)")
    return {
        "indicator_name": probe_indicator_name("insider_sell_actual"),
        "value": value_f,
        "fact_statement": str(metrics.get("fact_statement") or ""),
        "calculation_logic": str(metrics.get("calculation_logic") or ""),
        "source": src,
        "raw_metrics": raw_metrics,
    }


def build_etf_redemption_impact_node(metrics: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    """#24 ETF 被动资金冲击当量白盒节点。"""
    value = metrics.get("value")
    if value is None:
        raise ValueError("etf_redemption_impact value 缺失")
    value_f = round(float(value), 2)
    raw_metrics = dict(metrics.get("raw_metrics") or {})
    src = source or str(metrics.get("source") or "Tushare Pro Fund Share & Portfolio (T+1 Lag)")
    return {
        "indicator_name": probe_indicator_name("etf_redemption_impact"),
        "value": value_f,
        "fact_statement": str(metrics.get("fact_statement") or ""),
        "calculation_logic": str(metrics.get("calculation_logic") or ""),
        "source": src,
        "raw_metrics": raw_metrics,
    }


def build_indicator_node(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    if key == "qmt_atr_trailing":
        return build_qmt_atr_trailing_node(payload)
    if key == "volume_price_div":
        return build_volume_price_div_node(payload)
    if key == "smart_money_flow":
        return build_smart_money_flow_node(payload, source=str(payload.get("source") or ""))
    if key == "level2_super_order":
        return build_level2_super_order_node(payload, source=str(payload.get("source") or ""))
    if key == "margin_short_skew":
        return build_margin_short_skew_node(payload, source=str(payload.get("source") or ""))
    if key == "turnover_acceleration":
        return build_turnover_acceleration_node(payload, source=str(payload.get("source") or ""))
    if key == "block_trade_discount":
        return build_block_trade_discount_node(payload, source=str(payload.get("source") or ""))
    if key == "retail_concentration":
        return build_retail_concentration_node(payload, source=str(payload.get("source") or ""))
    if key == "insider_sell_actual":
        return build_insider_sell_actual_node(payload, source=str(payload.get("source") or ""))
    if key == "etf_redemption_impact":
        return build_etf_redemption_impact_node(payload, source=str(payload.get("source") or ""))
    val = payload.get("value")
    if val is None:
        raise ValueError(f"{key} value 缺失")
    name = probe_indicator_name(key)
    node: dict[str, Any] = {
        "value": val,
        "source": str(payload.get("source") or ""),
        "calculation_logic": str(payload.get("calculation_logic") or ""),
        "fact_statement": str(payload.get("fact_statement") or ""),
    }
    if name and name != key:
        node["indicator_name"] = name
    return node


def raw_metrics_for_display(node: dict[str, Any]) -> dict[str, Any]:
    """前端抽屉：新 raw_metrics 或旧平铺字段兼容。"""
    rm = node.get("raw_metrics")
    if isinstance(rm, dict) and rm:
        return dict(rm)
    out: dict[str, Any] = {}
    if node.get("atr_20") is not None or node.get("atr20") is not None:
        out["atr_20"] = _round2(node.get("atr_20", node.get("atr20")))
    if node.get("peak_price") is not None:
        out["peak_price"] = _round2(node.get("peak_price"))
    if node.get("current_price") is not None or node.get("current") is not None:
        out["current_price"] = _round2(node.get("current_price", node.get("current")))
    if node.get("last_tick_time"):
        out["last_tick_time"] = node.get("last_tick_time")
    return {k: v for k, v in out.items() if v is not None}
