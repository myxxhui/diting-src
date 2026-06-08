"""T1 批量 portfolio_signals 组装与兼容层。

[Ref: 28_ §4.1 · §4.2]
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from apps.copilot.modules.executing.money_unit import (
    attach_money_unit,
    format_pct_display,
    round_price,
)
from apps.copilot.modules.executing.profile import L3_KEYS, L4_KEYS, PROBE_KEYS


def _node(value: Any, source: str, logic: str, fact: str) -> dict[str, Any]:
    return {
        "value": value,
        "source": source,
        "calculation_logic": logic,
        "fact_statement": fact,
    }


def _symbol_exchange(symbol: str) -> str:
    sym = symbol.zfill(6)[-6:]
    suffix = "SH" if sym.startswith("6") else "SZ"
    return f"{sym}.{suffix}"


def _holding_status(position_pct: float | None) -> str | None:
    if position_pct is None:
        return None
    if position_pct >= 15:
        return "Heavy"
    if position_pct >= 5:
        return "Moderate"
    return "Light"


def _position_context(profit_context: dict[str, Any]) -> dict[str, Any] | None:
    return _position_context_batch(profit_context)


def _position_context_batch(profit_context: dict[str, Any]) -> dict[str, Any] | None:
    """批量 portfolio_signals.position_context（货币单位见 batch_meta.money_unit）。"""
    ctx: dict[str, Any] = {}
    if profit_context.get("opened_at"):
        ctx["entry_date"] = str(profit_context["opened_at"])[:10]
    if profit_context.get("cost_price"):
        ctx["cost_basis"] = round_price(profit_context["cost_price"])
    if profit_context.get("mark_price") is not None:
        ctx["current_price"] = round_price(profit_context["mark_price"])
    if profit_context.get("unrealized_pnl_pct") is not None:
        ctx["unrealized_profit_pct"] = format_pct_display(profit_context["unrealized_pnl_pct"])
    if profit_context.get("quantity") is not None:
        ctx["holding_volume"] = profit_context["quantity"]
    if profit_context.get("position_pct") is not None:
        ctx["position_pct"] = format_pct_display(profit_context["position_pct"])
    return ctx or None


def _probe_node_from_raw(key: str, raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """仅在有真实数据时返回四字段节点；否则 None（不虚构）。"""
    if not raw or not raw.get("ok"):
        return None
    payload = raw.get("payload") or {}
    source = raw.get("source") or ""

    if all(k in payload for k in ("value", "calculation_logic", "fact_statement")):
        val = payload.get("value")
        if val is None:
            return None
        return _node(
            val,
            payload.get("source") or source,
            str(payload["calculation_logic"]),
            str(payload["fact_statement"]),
        )

    if key == "qmt_atr_trailing":
        from apps.copilot.modules.executing.indicator_nodes import build_qmt_atr_trailing_node

        if payload.get("value") is None and payload.get("atr_multiple") is None:
            return None
        try:
            return build_qmt_atr_trailing_node({**payload, "source": payload.get("source") or source})
        except ValueError:
            return None
    if key == "volume_price_div":
        from apps.copilot.modules.executing.indicator_nodes import build_volume_price_div_node

        if payload.get("value") is None:
            return None
        try:
            merged = {**payload, "source": payload.get("source") or source}
            return build_volume_price_div_node(merged)
        except ValueError:
            return None
    if key == "smart_money_flow":
        try:
            from apps.copilot.modules.executing.smart_money_flow import compute_smart_money_metrics

            metrics = compute_smart_money_metrics(payload)
            node = _node(
                metrics["value_pct"],
                source,
                metrics["calculation_logic"],
                metrics["fact_statement"],
            )
            node["indicator_name"] = metrics["indicator_name"]
            node["raw_metrics"] = metrics["raw_metrics"]
            return node
        except Exception as exc:
            return _node(None, source, "Smart Money Delta 计算失败", str(exc))
    if key == "exchange_rate_impact":
        val = payload.get("usd_cny")
        if val is None:
            return None
        return _node(val, source, "USD/CNY现货", f"美元兑人民币 {val}")
    if key == "copper_cost_pressure":
        val = payload.get("pct_30d")
        if val is None:
            return None
        return _node(val, source, "沪铜30日涨跌幅", f"沪铜近30日涨跌 {val}%")
    if key == "mgmt_and_core_team":
        events = payload.get("events") or []
        return _node(
            len(events),
            source,
            "巨潮董监高公告扫描",
            f"人事相关 {len(events)} 条"
            if events
            else f"巨潮已扫{payload.get('titles_scanned', '?')}条·无董监高事件",
        )
    if key in ("gb200_iteration_node", "insider_sell_actual"):
        headlines = payload.get("matched_headlines") or []
        if not headlines and not payload.get("value"):
            return None
        val = payload.get("value", len(headlines))
        return _node(
            val,
            source,
            "公告/新闻关键词",
            f"匹配 {len(headlines)} 条相关标题" if headlines else str(payload.get("fact_statement", "")),
        )
    if key == "level2_super_order":
        val = payload.get("net_super_order_5d")
        if val is None:
            return None
        return _node(val, source, "东财超大单5日净额", f"超大单5日合计 {val}")
    if key == "cloud_capex_consensus":
        val = payload.get("total_capex_usd")
        if val is None:
            return None
        return _node(
            val,
            source,
            "SEC EDGAR 四云商 CapEx",
            f"四云商CapEx合计USD {val}（{payload.get('count')}家）",
        )
    if key == "inventory_turnover":
        val = payload.get("turnover_days") or payload.get("value")
        if val is None:
            return None
        return _node(val, source, "存货周转天数", str(payload.get("fact_statement", f"周转天数 {val}")))
    if key == "contract_liabilities":
        val = payload.get("qoq_pct") or payload.get("value")
        if val is None:
            return None
        return _node(val, source, "合同负债环比", str(payload.get("fact_statement", f"合同负债环比 {val}%")))
    if key == "gross_margin_trend":
        val = payload.get("gross_margin") or payload.get("value")
        if val is None:
            return None
        return _node(val, source, "毛利率", str(payload.get("fact_statement", f"毛利率 {val}")))

    scalar = payload.get("value")
    if scalar is None:
        return None
    return _node(
        scalar,
        source,
        str(payload.get("calculation_logic", f"T0 key={key}")),
        str(payload.get("fact_statement", f"已采集 {key}")),
    )


def _degraded_line(key: str, raw: dict[str, Any] | None) -> str:
    if raw and raw.get("blocker"):
        return f"{key} ({raw['blocker']})"
    if raw and not raw.get("ok"):
        return f"{key} (采集失败)"
    return f"{key} (未采集)"


def telemetry_probe_stats(telemetry: dict[str, Any]) -> dict[str, Any]:
    """从批量/单标的 T1 JSON 提取覆盖率（供 T2 / orchestrator）。"""
    if "portfolio_signals" in telemetry:
        filled_keys: set[str] = set()
        all_degraded: list[str] = []
        for code, sig in (telemetry.get("portfolio_signals") or {}).items():
            filled_keys |= set((sig.get("indicators") or {}).keys())
            all_degraded.extend(sig.get("degraded_probes") or [])
        missing = [k for k in PROBE_KEYS if k not in filled_keys]
        n_stocks = telemetry.get("batch_meta", {}).get("total_stocks_checked", 1)
        max_fill = len(PROBE_KEYS) * max(n_stocks, 1)
        integrity = f"{round(100 * len(filled_keys) / max(len(PROBE_KEYS), 1))}%"
        return {
            "filled": len(filled_keys),
            "missing": missing,
            "degraded_probes": all_degraded,
            "data_integrity": integrity,
            "total_stocks_checked": n_stocks,
            "system_status": telemetry.get("batch_meta", {}).get("system_status"),
        }

    l3 = telemetry.get("L3_business_fundamentals") or {}
    l4 = telemetry.get("L4_capital_game_microstructure") or {}
    present = set(l3) | set(l4)
    missing = [k for k in PROBE_KEYS if k not in present]
    meta = telemetry.get("meta_info") or {}
    health = meta.get("system_health") or {}
    return {
        "filled": len(present),
        "missing": missing,
        "degraded_probes": health.get("degraded_probes") or [],
        "data_integrity": health.get("data_integrity"),
    }


def stock_signal_from_legacy_telemetry(telemetry: dict[str, Any]) -> dict[str, Any] | None:
    """旧版 meta+L3+L4 转单条 portfolio_signals（兼容历史 audit）。"""
    meta = telemetry.get("meta_info") or {}
    sym = meta.get("symbol")
    if not sym:
        return None
    indicators: dict[str, Any] = {}
    for k, v in (telemetry.get("L3_business_fundamentals") or {}).items():
        indicators[k] = v
    for k, v in (telemetry.get("L4_capital_game_microstructure") or {}).items():
        indicators[k] = v
    out: dict[str, Any] = {
        "stock_name": meta.get("company_name") or sym,
        "indicators": indicators,
    }
    if meta.get("position_context"):
        out["position_context"] = meta["position_context"]
    if meta.get("system_health", {}).get("degraded_probes"):
        out["degraded_probes"] = meta["system_health"]["degraded_probes"]
    return out


def extract_stock_indicators(telemetry: dict[str, Any], symbol: str) -> dict[str, Any]:
    """从批量或旧版 telemetry 取单标的 indicators（供前端）。"""
    code = _symbol_exchange(symbol)
    if "portfolio_signals" in telemetry:
        sig = (telemetry.get("portfolio_signals") or {}).get(code) or {}
        return sig.get("indicators") or {}
    legacy = stock_signal_from_legacy_telemetry(telemetry)
    if legacy:
        return legacy.get("indicators") or {}
    l3 = telemetry.get("L3_business_fundamentals") or telemetry.get("L3_Business") or {}
    l4 = telemetry.get("L4_capital_game_microstructure") or telemetry.get("L4_Game") or {}
    return {**l3, **l4}


def build_telemetry(
    symbol: str,
    *,
    as_of: date,
    raw_by_key: dict[str, dict[str, Any]],
    profit_context: dict[str, Any],
    execution_id: str | None = None,
) -> dict[str, Any]:
    """同步路径：单标的批量 JSON（portfolio_signals 仅含 1 键）。"""
    sym = symbol.zfill(6)[-6:]
    code = _symbol_exchange(sym)
    indicators: dict[str, Any] = {}
    degraded: list[str] = []

    for key in PROBE_KEYS:
        raw = raw_by_key.get(key)
        node = _probe_node_from_raw(key, raw)
        if node is None:
            degraded.append(_degraded_line(key, raw))
        else:
            indicators[key] = node

    signal: dict[str, Any] = {
        "stock_name": profit_context.get("name") or sym,
        "indicators": indicators,
    }
    pos = _position_context_batch(profit_context)
    if pos:
        signal["position_context"] = pos
    if degraded:
        signal["degraded_probes"] = degraded

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    batch_id = execution_id or f"batch_task_{as_of.strftime('%Y%m%d')}_{datetime.now(timezone.utc).strftime('%H%M%S')}"

    batch_meta = attach_money_unit(
        {
            "execution_id": batch_id,
            "timestamp": ts,
            "total_stocks_checked": 1,
            "system_status": "Degraded" if degraded else "Nominal",
        }
    )
    return {
        "batch_meta": batch_meta,
        "portfolio_signals": {code: signal},
    }
