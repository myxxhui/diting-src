"""Z0-M1 宏观景气 T0 采集 · 全量历史序列 · Tushare 优先。

[Ref: 34_ §3.1 · z0_history_contract.yaml]
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from apps.copilot.metrics.collectors._series_util import df_to_series, metric_err, metric_ok
from apps.copilot.metrics.tushare_client import tushare_available, ts_call
from apps.copilot.modules.radar.t0.collectors._ak_util import ak_call

logger = logging.getLogger(__name__)

_HISTORY = {
    "M.macro.pmi": ("36个月", 24),
    "M.macro.cpi_ppi_spread": ("36个月", 24),
    "M.macro.gdp_yoy": ("12个季度", 8),
    "M.macro.social_financing": ("36个月", 24),
    "M.macro.m2_yoy": ("36个月", 24),
    "M.macro.us10y": ("24个月", 200),
    "M.macro.vix": ("3年", 200),
}


def _hist(metric_id: str) -> tuple[str, int]:
    return _HISTORY.get(metric_id, ("", 0))


def collect_pmi() -> dict[str, Any]:
    hr, min_pts = _hist("M.macro.pmi")
    if tushare_available():
        try:
            df = ts_call("cn_pmi")
            if df is not None and not df.empty:
                series = df_to_series(
                    df,
                    period_col="MONTH",
                    fields={"pmi": "PMI010000"},
                    tail=48,
                )
                row = df.iloc[0]
                pmi = float(row.get("PMI010000") or row.get("PMI020100") or 0)
                month = str(row.get("MONTH", ""))
                regime = "expansion" if pmi >= 50 else "contraction" if pmi < 49 else "neutral"
                return metric_ok(
                    "M.macro.pmi",
                    {"month": month, "pmi": pmi, "pmi_yoy_pct": None, "regime": regime},
                    "tushare:cn_pmi",
                    series=series,
                    history_required=hr,
                    min_points=min_pts,
                )
        except Exception as exc:  # noqa: BLE001
            ts_err = str(exc)[:120]
    else:
        ts_err = "TUSHARE_TOKEN 未配置"

    try:
        import akshare as ak
    except ImportError:
        return metric_err("M.macro.pmi", f"Tushare 不可用({ts_err}) · akshare 缺失")

    df = ak_call(ak.macro_china_pmi)
    if df is None or df.empty:
        return metric_err("M.macro.pmi", f"Tushare 失败({ts_err}) · akshare 空/超时")

    period_col = "月份" if "月份" in df.columns else df.columns[0]
    pmi_col = "制造业-指数" if "制造业-指数" in df.columns else None
    yoy_col = "制造业-同比增长" if "制造业-同比增长" in df.columns else None
    fields = {}
    if pmi_col:
        fields["pmi"] = pmi_col
    if yoy_col:
        fields["pmi_yoy_pct"] = yoy_col
    series = df_to_series(df, period_col=period_col, fields=fields, tail=48)

    row = df.iloc[0]
    pmi = float(row.get("制造业-指数", 0) or 0)
    yoy = float(row.get("制造业-同比增长", 0) or 0) if yoy_col else None
    return metric_ok(
        "M.macro.pmi",
        {
            "month": str(row.get("月份", "")),
            "pmi": pmi,
            "pmi_yoy_pct": yoy,
            "regime": "expansion" if pmi >= 50 else "contraction" if pmi < 49 else "neutral",
        },
        "akshare:macro_china_pmi",
        series=series,
        history_required=hr,
        min_points=min_pts,
    )


def collect_cpi_ppi_spread() -> dict[str, Any]:
    hr, min_pts = _hist("M.macro.cpi_ppi_spread")
    if tushare_available():
        try:
            cpi = ts_call("cn_cpi")
            ppi = ts_call("cn_ppi")
            if cpi is not None and not cpi.empty and ppi is not None and not ppi.empty:
                cpi_s = df_to_series(cpi, period_col="month", fields={"cpi_yoy_pct": "nt_yoy"}, tail=48)
                ppi_s = df_to_series(ppi, period_col="month", fields={"ppi_yoy_pct": "ppi_yoy"}, tail=48)
                spread_series: list[dict[str, Any]] = []
                ppi_map = {x["period"]: x.get("ppi_yoy_pct") for x in ppi_s}
                for item in cpi_s:
                    p = item["period"]
                    c = item.get("cpi_yoy_pct")
                    pv = ppi_map.get(p)
                    if c is not None and pv is not None:
                        spread_series.append(
                            {"period": p, "cpi_yoy_pct": c, "ppi_yoy_pct": pv, "spread_ppt": round(c - pv, 4)}
                        )
                cpi_yoy = float(cpi.iloc[0].get("nt_yoy", 0) or 0)
                ppi_yoy = float(ppi.iloc[0].get("ppi_yoy", 0) or 0)
                return metric_ok(
                    "M.macro.cpi_ppi_spread",
                    {
                        "cpi_yoy_pct": cpi_yoy,
                        "ppi_yoy_pct": ppi_yoy,
                        "spread_ppt": round(cpi_yoy - ppi_yoy, 4),
                        "cpi_month": str(cpi.iloc[0].get("month", "")),
                        "ppi_month": str(ppi.iloc[0].get("month", "")),
                    },
                    "tushare:cn_cpi+cn_ppi",
                    series=spread_series,
                    history_required=hr,
                    min_points=min_pts,
                )
        except Exception as exc:  # noqa: BLE001
            ts_err = str(exc)[:80]
    else:
        ts_err = "无 token"

    try:
        import akshare as ak
    except ImportError:
        return metric_err("M.macro.cpi_ppi_spread", f"tushare({ts_err}) · akshare 不可用")

    cpi_df = ak_call(ak.macro_china_cpi)
    ppi_df = ak_call(ak.macro_china_ppi)
    if cpi_df is None or cpi_df.empty or ppi_df is None or ppi_df.empty:
        return metric_err("M.macro.cpi_ppi_spread", f"tushare({ts_err}) · akshare CPI/PPI 失败")

    cpi_s = df_to_series(
        cpi_df, period_col="月份", fields={"cpi_yoy_pct": "全国-同比增长"}, tail=48
    )
    ppi_s = df_to_series(
        ppi_df, period_col="月份", fields={"ppi_yoy_pct": "当月同比增长"}, tail=48
    )
    ppi_map = {x["period"]: x.get("ppi_yoy_pct") for x in ppi_s}
    spread_series = []
    for item in cpi_s:
        p = item["period"]
        c = item.get("cpi_yoy_pct")
        pv = ppi_map.get(p)
        if c is not None and pv is not None:
            spread_series.append(
                {"period": p, "cpi_yoy_pct": c, "ppi_yoy_pct": pv, "spread_ppt": round(c - pv, 4)}
            )
    cpi_yoy = float(cpi_df.iloc[0].get("全国-同比增长", 0) or 0)
    ppi_yoy = float(ppi_df.iloc[0].get("当月同比增长", 0) or 0)
    return metric_ok(
        "M.macro.cpi_ppi_spread",
        {
            "cpi_yoy_pct": cpi_yoy,
            "ppi_yoy_pct": ppi_yoy,
            "spread_ppt": round(cpi_yoy - ppi_yoy, 4),
            "cpi_month": str(cpi_df.iloc[0].get("月份", "")),
            "ppi_month": str(ppi_df.iloc[0].get("月份", "")),
        },
        "akshare:macro_china_cpi+ppi",
        series=spread_series,
        history_required=hr,
        min_points=min_pts,
    )


def collect_gdp_yoy() -> dict[str, Any]:
    hr, min_pts = _hist("M.macro.gdp_yoy")
    if tushare_available():
        try:
            df = ts_call("cn_gdp")
            if df is not None and not df.empty:
                series = df_to_series(
                    df,
                    period_col="quarter",
                    fields={"gdp_yoy_pct": "gdp_yoy"},
                    tail=16,
                )
                latest = df.iloc[0]
                yoy = float(latest.get("gdp_yoy", 0) or 0)
                return metric_ok(
                    "M.macro.gdp_yoy",
                    {"quarter": str(latest.get("quarter", "")), "gdp_yoy_pct": yoy},
                    "tushare:cn_gdp",
                    series=series,
                    history_required=hr,
                    min_points=min_pts,
                )
        except Exception as exc:  # noqa: BLE001
            ts_err = str(exc)[:100]
    else:
        ts_err = "无 token"

    try:
        import akshare as ak
    except ImportError:
        return metric_err("M.macro.gdp_yoy", f"tushare({ts_err}) · akshare 不可用")

    df = ak_call(ak.macro_china_gdp)
    if df is None or df.empty:
        return metric_err("M.macro.gdp_yoy", f"tushare({ts_err}) · akshare GDP 空")

    period_col = "季度" if "季度" in df.columns else df.columns[0]
    yoy_col = next((c for c in df.columns if "同比" in str(c)), None)
    if not yoy_col:
        return metric_err("M.macro.gdp_yoy", "akshare GDP 缺同比列")
    series = df_to_series(df, period_col=period_col, fields={"gdp_yoy_pct": yoy_col}, tail=16)
    latest = df.iloc[0]
    return metric_ok(
        "M.macro.gdp_yoy",
        {"quarter": str(latest.get(period_col, "")), "gdp_yoy_pct": float(latest.get(yoy_col, 0) or 0)},
        "akshare:macro_china_gdp",
        series=series,
        history_required=hr,
        min_points=min_pts,
    )


def collect_social_financing() -> dict[str, Any]:
    hr, min_pts = _hist("M.macro.social_financing")
    if tushare_available():
        try:
            df = ts_call("sf_month")
            if df is not None and not df.empty:
                series = df_to_series(
                    df,
                    period_col="month",
                    fields={
                        "inc_month": "inc_month",
                        "inc_cumval": "inc_cumval",
                        "stk_endval": "stk_endval",
                    },
                    tail=48,
                )
                latest = df.iloc[0]
                return metric_ok(
                    "M.macro.social_financing",
                    {
                        "month": str(latest.get("month", "")),
                        "inc_month": float(latest.get("inc_month", 0) or 0),
                        "inc_cumval": float(latest.get("inc_cumval", 0) or 0),
                    },
                    "tushare:sf_month",
                    series=series,
                    history_required=hr,
                    min_points=min_pts,
                )
        except Exception as exc:  # noqa: BLE001
            ts_err = str(exc)[:100]
    else:
        ts_err = "无 token"

    try:
        import akshare as ak
    except ImportError:
        return metric_err("M.macro.social_financing", f"tushare({ts_err}) · akshare 不可用")

    df = ak_call(ak.macro_china_shrzgm)
    if df is None or df.empty:
        df = ak_call(ak.macro_china_new_financial_credit)
    if df is None or df.empty:
        return metric_err("M.macro.social_financing", f"tushare({ts_err}) · akshare 社融空")

    period_col = df.columns[0]
    val_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
    series = df_to_series(df, period_col=period_col, fields={"value": val_col}, tail=48)
    latest = df.iloc[0]
    return metric_ok(
        "M.macro.social_financing",
        {"month": str(latest.get(period_col, "")), "value": float(latest.get(val_col, 0) or 0)},
        "akshare:macro_china_shrzgm",
        series=series,
        history_required=hr,
        min_points=min_pts,
    )


def collect_m2_yoy() -> dict[str, Any]:
    hr, min_pts = _hist("M.macro.m2_yoy")
    if tushare_available():
        try:
            df = ts_call("cn_m")
            if df is not None and not df.empty:
                series = df_to_series(
                    df,
                    period_col="month",
                    fields={"m2_yoy_pct": "m2_yoy", "m2": "m2"},
                    tail=48,
                )
                latest = df.iloc[0]
                return metric_ok(
                    "M.macro.m2_yoy",
                    {
                        "month": str(latest.get("month", "")),
                        "m2_yoy_pct": float(latest.get("m2_yoy", 0) or 0),
                    },
                    "tushare:cn_m",
                    series=series,
                    history_required=hr,
                    min_points=min_pts,
                )
        except Exception as exc:  # noqa: BLE001
            ts_err = str(exc)[:100]
    else:
        ts_err = "无 token"

    try:
        import akshare as ak
    except ImportError:
        return metric_err("M.macro.m2_yoy", f"tushare({ts_err}) · akshare 不可用")

    df = ak_call(ak.macro_china_money_supply)
    if df is None or df.empty:
        return metric_err("M.macro.m2_yoy", f"tushare({ts_err}) · akshare M2 空")

    period_col = "月份" if "月份" in df.columns else df.columns[0]
    yoy_col = next((c for c in df.columns if "M2" in str(c) and "同比" in str(c)), None)
    if not yoy_col:
        yoy_col = next((c for c in df.columns if "同比" in str(c)), df.columns[-1])
    series = df_to_series(df, period_col=period_col, fields={"m2_yoy_pct": yoy_col}, tail=48)
    latest = df.iloc[0]
    return metric_ok(
        "M.macro.m2_yoy",
        {"month": str(latest.get(period_col, "")), "m2_yoy_pct": float(latest.get(yoy_col, 0) or 0)},
        "akshare:macro_china_money_supply",
        series=series,
        history_required=hr,
        min_points=min_pts,
    )


def collect_us10y() -> dict[str, Any]:
    hr, min_pts = _hist("M.macro.us10y")
    try:
        import akshare as ak
    except ImportError:
        return metric_err("M.macro.us10y", "akshare 不可用")

    df = ak_call(ak.bond_zh_us_rate)
    if df is None or df.empty:
        return metric_err("M.macro.us10y", "akshare bond_zh_us_rate 空/超时")

    period_col = "日期" if "日期" in df.columns else df.columns[0]
    y10_col = next((c for c in df.columns if "10" in str(c) and "年" in str(c)), None)
    if not y10_col:
        y10_col = df.columns[-1]
    series = df_to_series(df, period_col=period_col, fields={"us10y_pct": y10_col}, tail=600)
    latest = df.iloc[-1] if len(df) else df.iloc[0]
    val = float(latest.get(y10_col, 0) or 0)
    prev = float(df.iloc[-2].get(y10_col, val) or val) if len(df) >= 2 else val
    return metric_ok(
        "M.macro.us10y",
        {
            "date": str(latest.get(period_col, "")),
            "us10y_pct": val,
            "day_change_bp": round((val - prev) * 100, 2),
        },
        "akshare:bond_zh_us_rate",
        series=series,
        history_required=hr,
        min_points=min_pts,
    )


def collect_vix() -> dict[str, Any]:
    hr, min_pts = _hist("M.macro.vix")
    try:
        import akshare as ak
    except ImportError:
        return metric_err("M.macro.vix", "akshare 不可用")

    df = None
    source = ""
    for fn_name, src in (
        ("index_investing_global", "akshare:index_investing_global:VIX"),
        ("index_option_50etf_qvix", "akshare:index_option_50etf_qvix:proxy"),
    ):
        try:
            if fn_name == "index_investing_global":
                candidate = ak_call(
                    ak.index_investing_global,
                    country="美国",
                    index_name="VIX恐慌指数",
                    period="每日",
                    start_date="20200101",
                    end_date=datetime.now().strftime("%Y%m%d"),
                )
            else:
                candidate = ak_call(getattr(ak, fn_name))
            if candidate is not None and not candidate.empty:
                df = candidate
                source = src
                break
        except Exception:  # noqa: BLE001
            continue

    if df is None or df.empty:
        return metric_err("M.macro.vix", "VIX 数据源均不可用（CBOE 直连待扩展期）")

    period_col = df.columns[0]
    val_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
    series = df_to_series(df, period_col=period_col, fields={"vix": val_col}, tail=800)
    latest = df.iloc[-1]
    val = float(latest.get(val_col, 0) or 0)
    return metric_ok(
        "M.macro.vix",
        {"date": str(latest.get(period_col, "")), "vix": val},
        source,
        series=series,
        history_required=hr,
        min_points=min_pts,
    )


def collect_m1_bundle() -> dict[str, Any]:
    collectors = (
        collect_pmi,
        collect_cpi_ppi_spread,
        collect_gdp_yoy,
        collect_social_financing,
        collect_m2_yoy,
        collect_us10y,
        collect_vix,
    )
    parts: dict[str, Any] = {}
    seen: set[str] = set()
    for fn in collectors:
        snap = fn()
        mid = snap.get("metric_id")
        if not mid or mid in seen:
            continue
        seen.add(mid)
        parts[mid] = snap

    ok_count = sum(1 for p in parts.values() if p.get("status") == "ok")
    pmi_ok = (parts.get("M.macro.pmi") or {}).get("status") == "ok"
    return {
        "status": "ok" if pmi_ok and ok_count >= 3 else ("partial" if pmi_ok else "error"),
        "job_id": "z0-m1-macro",
        "parts": parts,
        "ok_count": ok_count,
        "detail": None if pmi_ok else "PMI 采集失败",
    }
