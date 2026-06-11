"""fii_twse_cloud T1 指标节点。

[Ref: 28_ §4.1 · indicator_nodes]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.executing.l3.fii_twse_cloud.card_strategy import build_card_strategy
from apps.copilot.modules.executing.l3.fii_twse_cloud.constants import HONHAI_MONTHLY_CATEGORY_PATH
from apps.copilot.modules.executing.l3.fii_twse_cloud.t1_contract import build_t1_contract
from apps.copilot.modules.executing.probe_labels import probe_indicator_name

_TWSE_MONTHLY = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"


def build_fii_twse_cloud_node(
    t0_payload: dict[str, Any],
    *,
    source: str,
    cloud_lo_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    contract = build_t1_contract(t0_payload)
    bounds = contract["cloud_revenue_ntd"]
    lo, hi, mid = int(bounds["lo"]), int(bounds["hi"]), int(bounds["mid"])
    mom = float(t0_payload["total_mom_pct"])
    total = int(t0_payload["total_revenue_ntd"])
    segments = contract.get("segments") or {}
    card_strategy = build_card_strategy(
        t0_payload,
        contract,
        cloud_lo_history=cloud_lo_history,
    )

    return {
        "indicator_name": probe_indicator_name("fii_twse_cloud"),
        "value": f"{mid / 1e9:.0f}亿",
        "value_detail": f"{lo/1e9:.1f}–{hi/1e9:.1f} 亿 NTD",
        "fact_statement": contract["fact_statement"],
        "calculation_logic": (
            f"R_total={total:,} NTD · MoM={mom:+.1f}% · "
            f"R_cloud∈[{lo:,}, {hi:,}] NTD"
        ),
        "source": source,
        "t1_json": contract,
        "raw_metrics": {
            "report_year": t0_payload.get("report_year"),
            "report_month": t0_payload.get("report_month"),
            "total_revenue_ntd": total,
            "total_mom_pct": mom,
            "total_yoy_pct": t0_payload.get("total_yoy_pct"),
            "cloud_revenue_lower_ntd": lo,
            "cloud_revenue_upper_ntd": hi,
            "cloud_revenue_mid_ntd": mid,
            "cloud_mom_rank": contract.get("pr_evidence", {}).get("cloud_mom_rank"),
            "segments": segments,
            "revenue_history": t0_payload.get("revenue_history") or [],
            "pr_raw_text": t0_payload.get("pr_raw_text") or "",
            "segment_baseline_weights_last_q": t0_payload.get("segment_baseline_weights_last_q") or {},
            "seasonality_factor_consumer": t0_payload.get("seasonality_factor_consumer") or {},
            "card_strategy": card_strategy,
            "sources": {
                "twse_monthly": _TWSE_MONTHLY,
                "ir_category": f"https://www.honhai.com{HONHAI_MONTHLY_CATEGORY_PATH}",
                "ir_article": t0_payload.get("article_url"),
                "ir_images": t0_payload.get("pr_image_urls") or [],
            },
        },
    }
