"""Z0-M5 流动性 T0/T1 采集 · Tushare 优先 · 3 年历史序列。

[Ref: 34_ §3.4 · 32_ §5B.7 · z0_history_contract.yaml]
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from apps.copilot.metrics.collectors._series_util import metric_err, metric_ok
from apps.copilot.metrics.tushare_client import tushare_available, ts_call
from apps.copilot.modules.radar.t0.collectors._ak_util import ak_call

_HISTORY = {
    "M.liq.north_net_20d": ("3年", 200),
    "M.liq.margin_balance": ("3年", 200),
}


def _hist(metric_id: str) -> tuple[str, int]:
    return _HISTORY.get(metric_id, ("", 0))


def _finite(v: Any) -> float | None:
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _trade_dates(days: int = 1200) -> tuple[str, str]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days + 60)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def collect_north_net_20d() -> dict[str, Any]:
    hr, min_pts = _hist("M.liq.north_net_20d")
    ts_err = ""
    if tushare_available():
        try:
            start, end = _trade_dates(1200)
            df = ts_call("moneyflow_hsgt", start_date=start, end_date=end)
            if df is not None and not df.empty:
                series: list[dict[str, Any]] = []
                for _, r in df.iterrows():
                    v = _finite(r.get("north_money"))
                    if v is not None:
                        series.append({"period": str(r.get("trade_date", "")), "north_money": v})
                if len(series) >= 3:
                    vals = [x["north_money"] for x in series]
                    scale = 100.0  # 百万元 → 亿元
                    net_20d = round(sum(vals[-20:]) / scale, 4)
                    net_5d = round(sum(vals[-5:]) / scale, 4)
                    # 附加滚动 20 日序列（亿元）供历史分析
                    roll_series: list[dict[str, Any]] = []
                    for i in range(19, len(series)):
                        window = vals[i - 19 : i + 1]
                        roll_series.append(
                            {
                                "period": series[i]["period"],
                                "net_20d_yi": round(sum(window) / scale, 4),
                            }
                        )
                    return metric_ok(
                        "M.liq.north_net_20d",
                        {
                            "net_20d_yi": net_20d,
                            "net_5d_yi": net_5d,
                            "valid_days": len(vals[-30:]),
                            "as_of_trade": series[-1]["period"],
                        },
                        "tushare:moneyflow_hsgt",
                        series=roll_series or series[-200:],
                        history_required=hr,
                        min_points=min_pts,
                    )
            ts_err = "moneyflow_hsgt 空"
        except Exception as exc:  # noqa: BLE001
            ts_err = str(exc)[:100]
    else:
        ts_err = "TUSHARE_TOKEN 未配置"

    try:
        import akshare as ak
    except ImportError:
        return metric_err("M.liq.north_net_20d", f"Tushare 失败({ts_err}) · akshare 不可用")

    df = ak_call(ak.stock_hsgt_hist_em, symbol="北向资金")
    if df is None or df.empty:
        return metric_err("M.liq.north_net_20d", f"Tushare({ts_err}) · akshare 北向空/超时")

    net_col = "当日成交净买额" if "当日成交净买额" in df.columns else None
    flow_col = "当日资金流入" if "当日资金流入" in df.columns else None
    use_col = net_col or flow_col
    if use_col is None:
        return metric_err("M.liq.north_net_20d", "北向数据列缺失")

    date_col = "日期" if "日期" in df.columns else df.columns[0]
    series_raw: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        v = _finite(r.get(use_col))
        if v is not None:
            series_raw.append({"period": str(r.get(date_col, "")), "flow": v})

    if len(series_raw) < 3:
        return metric_err("M.liq.north_net_20d", "北向有效交易日不足")

    vals = [x["flow"] for x in series_raw]
    scale = 1e8 if max(abs(v) for v in vals[-30:]) > 1e6 else 1.0
    net_20d = round(sum(vals[-20:]) / scale, 4)
    net_5d = round(sum(vals[-5:]) / scale, 4)
    roll_series = []
    for i in range(19, len(series_raw)):
        window = vals[i - 19 : i + 1]
        roll_series.append(
            {"period": series_raw[i]["period"], "net_20d_yi": round(sum(window) / scale, 4)}
        )
    return metric_ok(
        "M.liq.north_net_20d",
        {
            "net_20d_yi": net_20d,
            "net_5d_yi": net_5d,
            "valid_days": len(vals[-30:]),
            "as_of_trade": series_raw[-1]["period"],
        },
        "akshare:stock_hsgt_hist_em",
        series=roll_series[-800:] if roll_series else series_raw[-200:],
        history_required=hr,
        min_points=min_pts,
    )


def collect_margin_balance_trend() -> dict[str, Any]:
    hr, min_pts = _hist("M.liq.margin_balance")
    ts_err = ""
    if tushare_available():
        try:
            start, end = _trade_dates(1200)
            df = ts_call("margin", start_date=start, end_date=end)
            if df is not None and not df.empty:
                series: list[dict[str, Any]] = []
                for _, r in df.iterrows():
                    rz = _finite(r.get("rzye"))
                    if rz is not None:
                        series.append({"period": str(r.get("trade_date", "")), "balance": rz})
                if len(series) >= 5:
                    balances = [x["balance"] for x in series]
                    chg_pct = (
                        round((balances[-1] - balances[-20]) / balances[-20] * 100, 4)
                        if len(balances) >= 20 and balances[-20]
                        else round((balances[-1] - balances[0]) / balances[0] * 100, 4)
                        if balances[0]
                        else 0.0
                    )
                    return metric_ok(
                        "M.liq.margin_balance",
                        {
                            "balance_latest": balances[-1],
                            "change_20d_pct": chg_pct,
                            "valid_days": len(balances),
                            "as_of_trade": series[-1]["period"],
                        },
                        "tushare:margin",
                        series=series[-800:],
                        history_required=hr,
                        min_points=min_pts,
                    )
            ts_err = "margin 空"
        except Exception as exc:  # noqa: BLE001
            ts_err = str(exc)[:100]
    else:
        ts_err = "无 token"

    try:
        import akshare as ak
    except ImportError:
        return metric_err("M.liq.margin_balance", f"Tushare({ts_err}) · akshare 不可用")

    sse = ak_call(ak.stock_margin_sse)
    if sse is None or sse.empty:
        return metric_err("M.liq.margin_balance", f"Tushare({ts_err}) · akshare 两融空/超时")
    bal_col = next((c for c in sse.columns if "融资融券余额" in str(c)), None)
    if bal_col is None:
        bal_col = sse.columns[-1]
    date_col = "信用交易日期" if "信用交易日期" in sse.columns else sse.columns[0]
    series_ak: list[dict[str, Any]] = []
    for _, r in sse.iterrows():
        v = _finite(r.get(bal_col))
        if v is not None:
            series_ak.append({"period": str(r.get(date_col, "")), "balance": v})
    if len(series_ak) < 5:
        return metric_err("M.liq.margin_balance", "两融有效样本不足")
    balances = [x["balance"] for x in series_ak]
    chg_pct = round((balances[-1] - balances[0]) / balances[0] * 100, 4) if balances[0] else 0.0
    return metric_ok(
        "M.liq.margin_balance",
        {
            "balance_latest": balances[-1],
            "change_20d_pct": chg_pct,
            "valid_days": len(balances),
            "as_of_trade": series_ak[-1]["period"],
        },
        "akshare:stock_margin_sse",
        series=series_ak[-800:],
        history_required=hr,
        min_points=min_pts,
    )


def synthesize_liquidity_regime(
    north: dict[str, Any],
    pmi: dict[str, Any] | None = None,
    *,
    margin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """规则合成 P0′ liquidity_regime（禁止 LLM）。"""
    net_20 = None
    net_5 = None
    if north.get("status") == "ok":
        net_20 = (north.get("data") or {}).get("net_20d_yi")
        net_5 = (north.get("data") or {}).get("net_5d_yi")

    margin_chg = None
    if margin and margin.get("status") == "ok":
        margin_chg = (margin.get("data") or {}).get("change_20d_pct")

    if net_20 is None and margin_chg is None:
        return metric_err("M.liq.regime_composite", "缺少北向/两融 T0")

    regime = "neutral"
    p0_prime = False
    if net_20 is not None:
        if net_20 < -50 or (net_5 is not None and net_5 < -20):
            regime = "risk_off"
            p0_prime = True
        elif net_20 > 30 and (net_5 is None or net_5 > 0):
            regime = "risk_on"
        elif net_20 > 0:
            regime = "mild_inflow"
    elif margin_chg is not None:
        if margin_chg > 5:
            regime = "mild_inflow"
        elif margin_chg < -3:
            regime = "risk_off"
            p0_prime = True

    pmi_val = None
    if pmi and pmi.get("status") == "ok":
        pmi_val = (pmi.get("data") or {}).get("pmi")

    macro_regime = "pending"
    if pmi_val is not None:
        macro_regime = "expansion" if pmi_val >= 50 else "contraction"

    source = "rule:z0_liquidity_regime_v1"
    if net_20 is None and margin_chg is not None:
        source = "rule:z0_liquidity_regime_v1;margin_fallback"

    return metric_ok(
        "M.liq.regime_composite",
        {
            "liquidity_regime": regime,
            "p0_prime": p0_prime,
            "macro_regime": macro_regime,
            "inputs": {
                "north_net_20d_yi": net_20,
                "north_net_5d_yi": net_5,
                "margin_change_20d_pct": margin_chg,
                "pmi": pmi_val,
            },
        },
        source,
    )


def collect_m5_bundle(pmi_snap: dict[str, Any] | None = None) -> dict[str, Any]:
    north = collect_north_net_20d()
    margin = collect_margin_balance_trend()
    regime = synthesize_liquidity_regime(
        north,
        pmi_snap,
        margin=margin if margin.get("status") == "ok" else None,
    )
    ok = regime.get("status") == "ok"
    parts: dict[str, Any] = {
        "north_net_20d": north,
        "margin_balance": margin,
        "regime_composite": regime,
    }
    return {
        "status": "ok" if ok else "error",
        "job_id": "z0-m5-liquidity",
        "parts": parts,
        "ok_count": sum(1 for x in parts.values() if x.get("status") == "ok"),
        "detail": None if ok else "流动性采集/合成失败",
    }
