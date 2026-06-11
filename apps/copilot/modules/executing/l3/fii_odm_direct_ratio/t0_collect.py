"""T0 采集编排 · fii_odm_direct_ratio。

[Ref: 28_ §2.2 · l3-fii-odm-quarterly]
"""
from __future__ import annotations

import logging
import os
from typing import Any

from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.constants import (
    CUSTOMER_ARCHETYPE_DICTIONARY,
    DEFAULT_HISTORICAL_RATIO_BASELINE_PCT,
    DEFAULT_OTHER_SEGMENT_MAX_PCT,
    DEFAULT_TRADITIONAL_OEM_CAPEX_PROXY_PCT,
    OFFICIAL_SEGMENTS,
    PROBE_KEY,
)
from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.t0_cninfo import (
    fetch_cloud_segment_from_latest_report,
    fetch_qa_supplement,
)
from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.t1_semantic import (
    analyze_semantic_evidence,
)

logger = logging.getLogger(__name__)


def _block(code: str, reason: str) -> dict[str, Any]:
    return {"probe_key": PROBE_KEY, "ok": False, "blocker": f"[{code}] {reason}", "payload": None}


def _ok(payload: dict[str, Any], source: str) -> dict[str, Any]:
    return {"probe_key": PROBE_KEY, "ok": True, "blocker": None, "payload": payload, "source": source}


def collect_fii_odm_direct_ratio_t0(
    symbol: str = "601138",
    *,
    historical_ratio_baseline_pct: float | None = None,
) -> dict[str, Any]:
    """T0 双轨：巨潮财报结构化 + IR 实录 → DeepSeek 语义证据层。"""
    sym = symbol.zfill(6)[-6:]
    report = fetch_cloud_segment_from_latest_report(sym)
    if not report.get("ok"):
        return _block("T0", str(report.get("blocker") or "财报解析失败"))

    qa = fetch_qa_supplement(sym)
    ir_text = ""
    ir_title = ""
    if qa.get("ok") and qa.get("qa_raw_transcript"):
        ir_text = str(qa["qa_raw_transcript"])
        ir_title = str(qa.get("report_title") or "")

    report_excerpt = str(report.get("report_text_excerpt") or report.get("qa_raw_transcript") or "")

    semantic = analyze_semantic_evidence(
        report_excerpt=report_excerpt,
        ir_qa_text=ir_text,
        report_period=str(report.get("report_period") or ""),
        total_cloud_revenue_cny=int(report["total_cloud_revenue_cny"]),
        total_cloud_yoy_pct=report.get("total_cloud_yoy_pct"),
        ir_doc_title=ir_title,
    )

    baseline = historical_ratio_baseline_pct
    if baseline is None:
        baseline = DEFAULT_HISTORICAL_RATIO_BASELINE_PCT

    oem_proxy = float(
        os.environ.get(
            "EXECUTING_ODM_OEM_PROXY_PCT",
            str(DEFAULT_TRADITIONAL_OEM_CAPEX_PROXY_PCT),
        )
    )

    payload: dict[str, Any] = {
        "report_period": report.get("report_period"),
        "report_year": report.get("report_year"),
        "report_quarter": report.get("report_quarter"),
        "report_title": report.get("report_title"),
        "total_cloud_revenue_cny": report["total_cloud_revenue_cny"],
        "total_cloud_yoy_pct": report.get("total_cloud_yoy_pct"),
        "ai_server_revenue_cny": report.get("ai_server_revenue_cny"),
        "ai_server_pct": report.get("ai_server_pct"),
        "historical_ratio_baseline_pct": float(baseline),
        "traditional_oem_capex_proxy_pct": oem_proxy,
        "other_segment_max_pct": DEFAULT_OTHER_SEGMENT_MAX_PCT,
        "customer_archetype_dictionary": CUSTOMER_ARCHETYPE_DICTIONARY,
        "official_segments": [dict(s) for s in OFFICIAL_SEGMENTS],
        "report_text_excerpt": report_excerpt[:8000],
        "qa_raw_transcript": ir_text,
        "qa_doc_title": ir_title or None,
        "semantic_evidence_layer": semantic,
        "is_breakdown_published": bool(report.get("is_breakdown_published")),
        "odm_direct_ratio_published_pct": report.get("odm_direct_ratio_published_pct"),
        "pdf_chars": report.get("pdf_chars"),
        "qa_supplement_source": qa.get("source") if qa.get("ok") else None,
    }
    src = str(report.get("source") or "cninfo")
    if qa.get("ok"):
        src = f"{src}+{qa.get('source', 'ir_record')}"
    sem_tag = semantic.get("llm_tag") or "semantic"
    src = f"{src}+{sem_tag}"
    return _ok(payload, src)


def parse_baseline_from_t1_json(t1_json: dict[str, Any] | None) -> float | None:
    """从上一季 T1 契约读取占比基数（语义层保留兼容）。"""
    if not isinstance(t1_json, dict):
        return None
    ivr = t1_json.get("implied_value_range") or t1_json.get(
        "anti_substitution_matrix", {}
    ).get("implied_value_range", {})
    if not isinstance(ivr, dict):
        return None
    raw = ivr.get("calculated_lower_bound_ratio") or ivr.get("ratio_lower_pct")
    if raw is None or str(raw).strip() in ("—", "-", ""):
        return None
    s = str(raw).replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None
