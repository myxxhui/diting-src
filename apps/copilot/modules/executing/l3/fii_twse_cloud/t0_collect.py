"""T0 采集编排 · fii_twse_cloud。

[Ref: 28_ §2.2 · §3.4 l3-fii-twse-monthly]
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from apps.copilot.modules.executing.l3.fii_twse_cloud.constants import (
    HISTORICAL_TERM_DICTIONARY,
    OFFICIAL_SEGMENTS,
    PROBE_KEY,
    SEGMENT_BASELINE_WEIGHTS_LAST_Q,
)
from apps.copilot.modules.executing.l3.fii_twse_cloud.honhai_ir import _pr_text_usable, fetch_monthly_pr_text
from apps.copilot.modules.executing.l3.fii_twse_cloud.twse_client import (
    compute_consumer_seasonality,
    enrich_history_mom,
    fetch_finmind_history,
    fetch_twse_latest_monthly,
)

logger = logging.getLogger(__name__)

_MIN_HISTORY_MONTHS = 30  # ~3 年


def _block(code: str, reason: str) -> dict[str, Any]:
    return {"probe_key": PROBE_KEY, "ok": False, "blocker": f"[{code}] {reason}", "payload": None}


def _ok(payload: dict[str, Any], source: str) -> dict[str, Any]:
    return {"probe_key": PROBE_KEY, "ok": True, "blocker": None, "payload": payload, "source": source}


def collect_fii_twse_cloud_t0(
    *,
    twse_code: str = "2317",
    min_history_months: int = _MIN_HISTORY_MONTHS,
) -> dict[str, Any]:
    """T0 主干 + 辅助 · 无 mock。"""
    code = twse_code.replace(".TW", "").strip()
    try:
        trunk = fetch_twse_latest_monthly(code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("TWSE 月营收失败: %s", exc)
        return _block("B", f"TWSE OpenAPI 2317 月营收失败: {exc}"[:180])

    y, m = trunk["report_year"], trunk["report_month"]
    start = date(y - 3, m, 1)
    try:
        history = fetch_finmind_history(code, start_date=start)
    except Exception as exc:  # noqa: BLE001
        return _block("B", f"FinMind 历史月营收失败: {exc}"[:180])

    if len(history) < min_history_months:
        return _block(
            "C",
            f"历史月营收不足 {min_history_months} 月（实际 {len(history)}）· 无法校准词表/季节性",
        )

    history = enrich_history_mom(history)
    seasonality = compute_consumer_seasonality(history)

    try:
        ir = fetch_monthly_pr_text(year=y, month=m)
    except Exception as exc:  # noqa: BLE001
        return _block("B", f"鸿海 IR 月营收简报失败: {exc}"[:180])

    pr_raw_text = (ir.get("pr_raw_text") or "").strip()
    if not _pr_text_usable(pr_raw_text):
        imgs = ir.get("pr_image_urls") or []
        if imgs:
            return _block(
                "B",
                "营收简报为图片且 OCR 未产出可用板块文本 · 请确认 tesseract-ocr-chi-tra",
            )
        return _block("B", "鸿海 IR 未找到当月营收简报可用正文")

    payload: dict[str, Any] = {
        "report_year": y,
        "report_month": m,
        "twse_code": code,
        "total_revenue_ntd": trunk["total_revenue_ntd"],
        "total_mom_pct": trunk["total_mom_pct"],
        "total_yoy_pct": trunk["total_yoy_pct"],
        "prev_month_revenue_ntd": trunk["prev_month_revenue_ntd"],
        "pr_raw_text": pr_raw_text,
        "pr_image_urls": ir.get("pr_image_urls") or [],
        "pr_ocr_pages": ir.get("pr_ocr_pages") or [],
        "article_id": ir.get("article_id"),
        "article_url": ir.get("article_url"),
        "historical_term_dictionary": HISTORICAL_TERM_DICTIONARY,
        "segment_baseline_weights_last_q": dict(SEGMENT_BASELINE_WEIGHTS_LAST_Q),
        "seasonality_factor_consumer": seasonality,
        "official_segment_dictionary": [
            {"key": s["key"], "zh": s["zh"], "en": s["en"]} for s in OFFICIAL_SEGMENTS
        ],
        "revenue_history": history[-36:],
        "trunk_source": trunk["source"],
        "ir_source": ir.get("source"),
    }
    source = f"{trunk['source']} + {ir.get('source', 'Hon Hai IR')}"
    return _ok(payload, source)
