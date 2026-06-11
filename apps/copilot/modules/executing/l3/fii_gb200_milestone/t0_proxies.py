"""T0 物理影子指标 · Chroma 测试机台 + FII 原材料备料。

[Ref: 28_ §2.2 fii_gb200_milestone · Proxy Constrainment v2]
"""
from __future__ import annotations

import logging
import re
import statistics
from datetime import datetime, timezone, timedelta
from typing import Any

from apps.copilot.modules.executing.l3.fii_gb200_milestone.constants import (
    BASELINE_LOOKBACK_MONTHS,
    CHROMA_MOM_SURGE_PCT,
    CHROMA_TWSE_CODE,
    PROXY_SPIKE_THRESHOLD,
    RAW_MATERIALS_QOQ_SURGE_PCT,
    baseline_window_meta,
    baseline_window_start,
    event_window_meta,
    event_window_start,
    is_within_event_window,
)

logger = logging.getLogger(__name__)
_CST = timezone(timedelta(hours=8))

_RAW_MAT_ROW = re.compile(
    r"原材料\s+(?P<curr>[\d,]+)\s+(?P<prior>[\d,]+)",
)
_RAW_MAT_NARR = re.compile(
    r"原材料.{0,40}?(?:期末|账面).{0,20}?(?P<amount>[\d,，.]+)\s*(?:万元|元|万|亿)",
)


def _valid_report_date(pub: str) -> bool:
    try:
        parsed = datetime.strptime(pub[:10], "%Y-%m-%d")
        return 2000 <= parsed.year <= 2035
    except ValueError:
        return False


def _qian_to_cny(qian_str: str) -> float:
    return float(str(qian_str).replace(",", "").replace("，", "")) * 1e3


def _baseline_mom_stats(hist: list[dict[str, Any]]) -> dict[str, Any]:
    moms: list[float] = []
    for row in hist:
        try:
            moms.append(float(row.get("month_growth_rate") or row.get("mom_pct") or 0))
        except (TypeError, ValueError):
            continue
    if not moms:
        return {"sample_months": 0}
    moms_sorted = sorted(moms)
    p95_idx = max(0, int(len(moms_sorted) * 0.95) - 1)
    return {
        "sample_months": len(moms),
        "mom_median_pct": round(statistics.median(moms), 2),
        "mom_p95_pct": round(moms_sorted[p95_idx], 2),
        "mom_max_pct": round(max(moms), 2),
        "calibrated_threshold_mom_pct": CHROMA_MOM_SURGE_PCT,
    }


def fetch_chroma_test_equipment_proxy() -> dict[str, Any]:
    """致茂 2360.TW · 月营收 + 36 个月基准斜率 + MoM 极值检测。"""
    from apps.copilot.modules.executing.l3.fii_twse_cloud.twse_client import (
        fetch_finmind_history,
        fetch_twse_latest_monthly,
    )

    code = CHROMA_TWSE_CODE
    try:
        trunk = fetch_twse_latest_monthly(code)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "blocker": f"Chroma TWSE 月营收失败: {exc}"[:120]}

    end = datetime.now(_CST).date()
    baseline_start = baseline_window_start().date()
    try:
        hist = fetch_finmind_history(code, start_date=baseline_start, end_date=end)
    except Exception as exc:  # noqa: BLE001
        hist = []

    mom = float(trunk.get("total_mom_pct") or 0)
    baseline = _baseline_mom_stats(hist)
    surge = mom >= CHROMA_MOM_SURGE_PCT
    rev = trunk.get("total_revenue_ntd")
    return {
        "ok": True,
        "source": str(trunk.get("source") or "TWSE/FinMind"),
        "twse_code": code,
        "report_year": trunk.get("report_year"),
        "report_month": trunk.get("report_month"),
        "proxy_chroma_revenue_ntd": rev,
        "revenue_ntd": rev,
        "proxy_chroma_mom_pct": round(mom, 2),
        "mom_pct": round(mom, 2),
        "baseline_slope": baseline,
        "baseline_window": baseline_window_meta(),
        "history_months": len(hist),
        "recent_monthly_history": hist[-12:] if hist else [],
        "surge_signal": surge,
        "thresholds": PROXY_SPIKE_THRESHOLD,
        "interpretation_zh": (
            f"致茂 MoM {mom:.1f}% ≥ {CHROMA_MOM_SURGE_PCT:.0f}% · 测试机链爆发"
            if surge
            else f"致茂 MoM {mom:.1f}% · 未达 {CHROMA_MOM_SURGE_PCT:.0f}% 阈"
        ),
    }


def _parse_raw_materials_from_report(text: str) -> tuple[float | None, float | None]:
    head = text[:25000]
    m = _RAW_MAT_ROW.search(head)
    if m:
        try:
            return _qian_to_cny(m.group("curr")), _qian_to_cny(m.group("prior"))
        except ValueError:
            pass
    nm = _RAW_MAT_NARR.search(head)
    if nm:
        raw = nm.group("amount")
        try:
            val = float(raw.replace(",", "").replace("，", ""))
            if "亿" in nm.group(0):
                val *= 1e8
            elif "万" in nm.group(0):
                val *= 1e4
            return val, None
        except ValueError:
            pass
    return None, None


def _latest_report_item_in_window(symbol: str) -> dict[str, Any] | None:
    """巨潮 · 近 36 个月内最新定期报告（季报/年报）。"""
    from apps.cryo_guard.cninfo_client import iter_cninfo_announcements
    from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.t0_cninfo import _REPORT_TITLE, _SKIP_TITLE

    end = datetime.now(_CST)
    start = baseline_window_start(ref=end)
    best: dict[str, Any] | None = None
    best_key = ""
    for item in iter_cninfo_announcements(
        symbol,
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        category="",
        keyword="",
        max_pages=8,
        throttle_sec=0.25,
    ):
        title = str(item.get("announcementTitle") or "")
        if _SKIP_TITLE.search(title):
            continue
        if not _REPORT_TITLE.search(title):
            continue
        pub = str(item.get("announcementTime") or "")[:10]
        if pub and not _valid_report_date(pub):
            continue
        key = pub or title
        if key > best_key:
            best_key = key
            best = item
    return best


def fetch_fii_raw_materials_proxy(symbol: str = "601138") -> dict[str, Any]:
    """巨潮季报 · 存货-原材料绝对值 + QoQ。"""
    from apps.cryo_guard.cninfo_client import fetch_cninfo_adjunct_pdf_text

    sym = symbol.zfill(6)[-6:]
    item = _latest_report_item_in_window(sym)
    if not item:
        return {"ok": False, "blocker": "近36个月巨潮未找到定期报告·原材料影子不可用"}

    title = str(item.get("announcementTitle") or "")
    text = fetch_cninfo_adjunct_pdf_text(item.get("adjunctUrl"), item.get("adjunctType"))
    if not text or len(text) < 800:
        return {"ok": False, "blocker": "季报 PDF 过短·无法解析原材料", "report_title": title}

    curr, prior = _parse_raw_materials_from_report(text)
    if curr is None:
        return {
            "ok": False,
            "blocker": "季报未解析到原材料行（需存货分类附注）",
            "report_title": title,
        }

    qoq_pct: float | None = None
    if prior and prior > 0:
        qoq_pct = (curr - prior) / prior * 100.0

    surge = qoq_pct is not None and qoq_pct >= RAW_MATERIALS_QOQ_SURGE_PCT
    pub = str(item.get("announcementTime") or "")[:10]
    return {
        "ok": True,
        "source": "cninfo:periodic_report_pdf",
        "report_title": title,
        "published_date": pub or None,
        "proxy_fii_raw_materials_cny": int(curr),
        "raw_materials_cny": int(curr),
        "prior_raw_materials_cny": int(prior) if prior else None,
        "proxy_fii_raw_material_qoq_pct": round(qoq_pct, 2) if qoq_pct is not None else None,
        "qoq_pct": round(qoq_pct, 2) if qoq_pct is not None else None,
        "surge_signal": surge,
        "threshold_qoq_pct": RAW_MATERIALS_QOQ_SURGE_PCT,
        "event_window": event_window_meta(),
        "interpretation_zh": (
            f"原材料 QoQ +{qoq_pct:.1f}% · 超级大单备料"
            if surge and qoq_pct is not None
            else (
                f"原材料 QoQ {qoq_pct:.1f}% · 未达 {RAW_MATERIALS_QOQ_SURGE_PCT:.0f}% 阈"
                if qoq_pct is not None
                else "原材料绝对值已采集·缺环比基期"
            )
        ),
    }


def collect_shadow_proxies(symbol: str = "601138") -> dict[str, Any]:
    """双影子主链路 · Chroma + 原材料（v2 契约核心）。"""
    chroma = fetch_chroma_test_equipment_proxy()
    raw_mat = fetch_fii_raw_materials_proxy(symbol)
    active = sum(
        1
        for p in (chroma, raw_mat)
        if p.get("ok") and p.get("surge_signal")
    )
    return {
        "chroma_test_equipment": chroma,
        "raw_materials_inventory": raw_mat,
        "active_proxy_count": active,
        "proxy_confidence": "high" if active >= 2 else ("medium" if active == 1 else "low"),
        "proxy_spike_threshold": PROXY_SPIKE_THRESHOLD,
        "baseline_window": baseline_window_meta(),
        "event_window": event_window_meta(),
    }
