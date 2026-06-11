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
    trunk_from_finmind_history,
)

logger = logging.getLogger(__name__)

_MIN_HISTORY_MONTHS = 30  # ~3 年


def _block(code: str, reason: str) -> dict[str, Any]:
    return {"probe_key": PROBE_KEY, "ok": False, "blocker": f"[{code}] {reason}", "payload": None}


def _ok(payload: dict[str, Any], source: str) -> dict[str, Any]:
    return {"probe_key": PROBE_KEY, "ok": True, "blocker": None, "payload": payload, "source": source}


def _reconcile_trunk_with_history(
    trunk: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    """FinMind 历史常比 TWSE OpenAPI t187ap05_L 早 1 个月更新 · 取较新者作主档。"""
    if not history:
        return trunk
    last = history[-1]
    ly, lm = int(last["year"]), int(last["month"])
    ty, tm = int(trunk["report_year"]), int(trunk["report_month"])
    if (ly, lm) <= (ty, tm):
        return trunk
    prev_rev = int(history[-2]["total_revenue_ntd"]) if len(history) >= 2 else trunk.get(
        "prev_month_revenue_ntd"
    )
    yoy_pct = trunk.get("total_yoy_pct")
    for h in history:
        if int(h["year"]) == ly - 1 and int(h["month"]) == lm:
            base = int(h["total_revenue_ntd"])
            if base > 0:
                yoy_pct = (int(last["total_revenue_ntd"]) - base) / base * 100.0
            break
    logger.info(
        "FinMind %s-%02d 新于 TWSE %s-%02d · 主档改用 FinMind",
        ly,
        lm,
        ty,
        tm,
    )
    return {
        **trunk,
        "report_year": ly,
        "report_month": lm,
        "total_revenue_ntd": int(last["total_revenue_ntd"]),
        "prev_month_revenue_ntd": prev_rev,
        "total_mom_pct": last.get("total_mom_pct", trunk.get("total_mom_pct")),
        "total_yoy_pct": yoy_pct,
        "source": (
            f"FinMind TaiwanStockMonthRevenue (TWSE t187ap05_L 仍停在 {ty}-{tm:02d})"
        ),
    }


def collect_fii_twse_cloud_t0(
    *,
    twse_code: str = "2317",
    min_history_months: int = _MIN_HISTORY_MONTHS,
) -> dict[str, Any]:
    """T0 主干 + 辅助 · 无 mock。"""
    code = twse_code.replace(".TW", "").strip()
    trunk: dict[str, Any] | None = None
    twse_err: Exception | None = None
    try:
        trunk = fetch_twse_latest_monthly(code)
    except Exception as exc:  # noqa: BLE001
        twse_err = exc
        logger.warning("TWSE 月营收失败，尝试 FinMind 降级: %s", exc)

    if trunk is not None:
        y, m = trunk["report_year"], trunk["report_month"]
        start = date(y - 3, m, 1)
    else:
        today = date.today()
        start = date(today.year - 4, today.month, 1)

    try:
        history = fetch_finmind_history(code, start_date=start)
    except Exception as exc:  # noqa: BLE001
        if twse_err is not None:
            return _block(
                "B",
                f"TWSE 与 FinMind 均失败: TWSE={twse_err}; FinMind={exc}"[:180],
            )
        return _block("B", f"FinMind 历史月营收失败: {exc}"[:180])

    if trunk is None:
        try:
            history = enrich_history_mom(history)
            trunk = trunk_from_finmind_history(history)
            logger.info(
                "TWSE 不可用 · 主档改用 FinMind %s-%02d",
                trunk["report_year"],
                trunk["report_month"],
            )
        except Exception as exc:  # noqa: BLE001
            return _block("B", f"TWSE 失败且 FinMind 主档不可用: {twse_err}; {exc}"[:180])

    if len(history) < min_history_months:
        return _block(
            "C",
            f"历史月营收不足 {min_history_months} 月（实际 {len(history)}）· 无法校准词表/季节性",
        )

    history = enrich_history_mom(history)
    seasonality = compute_consumer_seasonality(history)

    trunk = _reconcile_trunk_with_history(trunk, history)
    y, m = trunk["report_year"], trunk["report_month"]

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
