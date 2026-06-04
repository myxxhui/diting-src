"""T1 feature_node 组装。

[Ref: 28_ §5.1]
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from apps.copilot.modules.executing.profile import L3_KEYS, L4_KEYS, PROBE_KEYS


def _node(value: Any, source: str, logic: str, fact: str) -> dict[str, Any]:
    return {
        "value": value,
        "source": source,
        "calculation_logic": logic,
        "fact_statement": fact,
    }


def build_telemetry(
    symbol: str,
    *,
    as_of: date,
    raw_by_key: dict[str, dict[str, Any]],
    profit_context: dict[str, Any],
) -> dict[str, Any]:
    l3: dict[str, Any] = {}
    l4: dict[str, Any] = {}
    missing: list[str] = []
    blockers: list[dict[str, str]] = []

    for key in PROBE_KEYS:
        raw = raw_by_key.get(key)
        if not raw or not raw.get("ok"):
            missing.append(key)
            if raw and raw.get("blocker"):
                blockers.append({"key": key, "reason": str(raw["blocker"])})
            node = _node(None, raw.get("source", "") if raw else "", "未采集", "无数据")
        else:
            payload = raw.get("payload") or {}
            source = raw.get("source", "HK Pod")
            if key == "qmt_atr_trailing":
                m = payload.get("atr_multiple")
                node = _node(
                    m,
                    source,
                    f"ATR20={payload.get('atr20')} peak={payload.get('peak_price')} cur={payload.get('current')}",
                    f"距高点回撤 {m} 倍ATR（20日）" if m is not None else "ATR不可用",
                )
            elif key == "volume_price_div":
                r = payload.get("ratio")
                node = _node(
                    r,
                    source,
                    "10日上涨日量/下跌日量",
                    f"量价比值 {r}" if r is not None else "量比不可用",
                )
            elif key == "northbound_net_flow":
                n = payload.get("net_3d_shares_change")
                node = _node(n, source, "近3日持股变化合计", f"北向3日持股变化 {n}")
            elif key == "exchange_rate_impact":
                node = _node(
                    payload.get("usd_cny"),
                    source,
                    "USD/CNY现货",
                    f"美元兑人民币 {payload.get('usd_cny')}",
                )
            elif key == "copper_cost_pressure":
                node = _node(
                    payload.get("pct_30d"),
                    source,
                    "沪铜30日涨跌幅",
                    f"沪铜近30日涨跌 {payload.get('pct_30d')}%",
                )
            elif key == "mgmt_and_core_team":
                events = payload.get("events") or []
                node = _node(
                    len(events),
                    source,
                    "巨潮董监高",
                    f"人事相关 {len(events)} 条"
                    if events
                    else f"巨潮已扫{payload.get('titles_scanned', '?')}条·无董监高事件",
                )
            elif key in ("gb200_iteration_node", "insider_sell_actual"):
                headlines = payload.get("matched_headlines") or []
                node = _node(
                    len(headlines),
                    source,
                    "公告/新闻关键词",
                    f"匹配 {len(headlines)} 条相关标题",
                )
            elif key == "level2_super_order":
                node = _node(
                    payload.get("net_super_order_5d"),
                    source,
                    "东财超大单5日净额",
                    f"超大单5日合计 {payload.get('net_super_order_5d')}",
                )
            elif key == "cloud_capex_consensus":
                node = _node(
                    payload.get("total_capex_usd"),
                    source,
                    "SEC EDGAR 四云商 CapEx",
                    f"四云商CapEx合计USD {payload.get('total_capex_usd')}（{payload.get('count')}家）",
                )
            else:
                node = _node(
                    json.dumps(payload, ensure_ascii=False)[:500],
                    source,
                    f"T0 payload 摘要 key={key}",
                    f"已采集 {key} 原始指标",
                )
        if key in L3_KEYS:
            l3[key] = node
        else:
            l4[key] = node

    return {
        "symbol": symbol.zfill(6)[-6:],
        "as_of": as_of.isoformat(),
        "profit_context": profit_context,
        "L3_Business": l3,
        "L4_Game": l4,
        "unavailable_data": missing,
        "blockers": blockers,
    }
