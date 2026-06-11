"""TWSE OpenAPI + FinMind 月营收历史。

[Ref: 28_ §2.2 fii_twse_cloud · T0 主干]
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import requests

from apps.copilot.modules.executing.l3.fii_twse_cloud.constants import (
    FINMIND_MONTHLY,
    TWSE_OPENAPI_MONTHLY,
)

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Diting-Copilot/1.0 (executing; fii_twse_cloud)"}
_TIMEOUT = 90.0


def _roc_ym_to_ce(roc_ym: str) -> tuple[int, int]:
    """11504 → (2026, 4)"""
    s = str(roc_ym).strip()
    if len(s) < 5:
        raise ValueError(f"无效 ROC 年月: {roc_ym}")
    roc_y = int(s[:3])
    month = int(s[3:])
    return roc_y + 1911, month


def _thousands_to_ntd(thousands: str | int | float) -> int:
    return int(float(str(thousands).replace(",", "")) * 1000)


def fetch_twse_latest_monthly(stock_code: str) -> dict[str, Any]:
    """TWSE OpenAPI t187ap05_L · 当月全市场月营收（取单股）。"""
    code = stock_code.replace(".TW", "").strip()
    resp = requests.get(TWSE_OPENAPI_MONTHLY, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    rows = resp.json()
    if not isinstance(rows, list):
        raise ValueError("TWSE t187ap05_L 非 list")
    hit = next((r for r in rows if str(r.get("公司代號", "")).strip() == code), None)
    if hit is None:
        raise ValueError(f"TWSE 未找到 {code} 当月营收")
    ce_y, ce_m = _roc_ym_to_ce(str(hit["資料年月"]))
    rev = _thousands_to_ntd(hit["營業收入-當月營收"])
    prev = _thousands_to_ntd(hit["營業收入-上月營收"])
    yoy_base = _thousands_to_ntd(hit["營業收入-去年當月營收"])
    mom = float(hit["營業收入-上月比較增減(%)"])
    yoy = float(hit["營業收入-去年同月增減(%)"])
    return {
        "report_year": ce_y,
        "report_month": ce_m,
        "total_revenue_ntd": rev,
        "prev_month_revenue_ntd": prev,
        "yoy_base_revenue_ntd": yoy_base,
        "total_mom_pct": mom,
        "total_yoy_pct": yoy,
        "source": "TWSE OpenAPI t187ap05_L",
        "raw_row": hit,
    }


def fetch_finmind_history(
    stock_code: str,
    *,
    start_date: date,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    """FinMind TaiwanStockMonthRevenue · 3 年回填（源自 TWSE/MOPS 公开数据）。"""
    code = stock_code.replace(".TW", "").strip()
    end = end_date or date.today()
    params = {
        "dataset": "TaiwanStockMonthRevenue",
        "data_id": code,
        "start_date": start_date.isoformat(),
        "end_date": end.isoformat(),
    }
    resp = requests.get(FINMIND_MONTHLY, params=params, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json().get("data") or []
    out: list[dict[str, Any]] = []
    for row in data:
        y = int(row["revenue_year"])
        m = int(row["revenue_month"])
        rev = int(row["revenue"])
        out.append(
            {
                "year": y,
                "month": m,
                "total_revenue_ntd": rev,
                "source": "FinMind TaiwanStockMonthRevenue",
            }
        )
    out.sort(key=lambda x: (x["year"], x["month"]))
    return out


def trunk_from_finmind_history(history: list[dict[str, Any]]) -> dict[str, Any]:
    """TWSE OpenAPI 不可用时的主档降级 · 取 FinMind 最新月。"""
    if not history:
        raise ValueError("FinMind 历史为空，无法构造主档")
    last = history[-1]
    ly, lm = int(last["year"]), int(last["month"])
    prev_rev = int(history[-2]["total_revenue_ntd"]) if len(history) >= 2 else None
    mom = last.get("total_mom_pct")
    yoy = None
    for h in history:
        if int(h["year"]) == ly - 1 and int(h["month"]) == lm:
            base = int(h["total_revenue_ntd"])
            if base > 0:
                yoy = (int(last["total_revenue_ntd"]) - base) / base * 100.0
            break
    return {
        "report_year": ly,
        "report_month": lm,
        "total_revenue_ntd": int(last["total_revenue_ntd"]),
        "prev_month_revenue_ntd": prev_rev,
        "total_mom_pct": mom,
        "total_yoy_pct": yoy,
        "source": "FinMind TaiwanStockMonthRevenue (TWSE OpenAPI 不可用降级)",
    }


def enrich_history_mom(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为历史序列补 MoM。"""
    by_key = {(h["year"], h["month"]): h for h in history}
    enriched: list[dict[str, Any]] = []
    for h in history:
        y, m = h["year"], h["month"]
        py, pm = (y - 1, m) if m > 1 else (y, m - 1)
        if m == 1:
            py, pm = y - 1, 12
        prev = by_key.get((py, pm))
        mom = None
        if prev and prev["total_revenue_ntd"] > 0:
            mom = (h["total_revenue_ntd"] - prev["total_revenue_ntd"]) / prev["total_revenue_ntd"] * 100.0
        enriched.append({**h, "total_mom_pct": mom})
    return enriched


def compute_consumer_seasonality(history: list[dict[str, Any]]) -> dict[str, Any]:
    """消费智能季节性极值：用总营收同月 MoM 分布作 iPhone 旺季代理。"""
    by_month: dict[int, list[float]] = {}
    for h in history:
        mom = h.get("total_mom_pct")
        if mom is None:
            continue
        by_month.setdefault(h["month"], []).append(float(mom))
    month_ranges: dict[str, list[float]] = {}
    all_moms: list[float] = []
    for m, vals in by_month.items():
        if not vals:
            continue
        lo, hi = min(vals), max(vals)
        month_ranges[str(m)] = [lo, hi]
        all_moms.extend(vals)
    if not all_moms:
        return {"consumer_mom_pct_range": [-20.0, 40.0], "by_calendar_month": month_ranges}
    return {
        "consumer_mom_pct_range": [min(all_moms), max(all_moms)],
        "by_calendar_month": month_ranges,
        "sample_months": len(all_moms),
    }
