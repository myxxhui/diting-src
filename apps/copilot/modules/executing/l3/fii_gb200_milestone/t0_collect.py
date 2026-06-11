"""T0 采集编排 · fii_gb200_milestone DeepSea 传感器层。

[Ref: 28_ §2.2 · §3.4 l3-fii-dynamic · earnings_transcript/cninfo_announcement]
"""
from __future__ import annotations

import logging
import re
from typing import Any

from apps.copilot.modules.executing.l3.fii_gb200_milestone.constants import (
    BASELINE_LOOKBACK_MONTHS,
    EVENT_LOOKBACK_MONTHS,
    EXPECTED_SEGMENTS,
    NPI_STATE_DICTIONARY,
    PROBE_KEY,
    PROXY_SPIKE_THRESHOLD,
    baseline_window_meta,
    event_window_meta,
    upstream_bottleneck_date,
)
from apps.copilot.modules.executing.l3.fii_gb200_milestone.t0_cninfo import (
    fetch_gb200_official_event,
    fetch_investor_relations_qa,
)
from apps.copilot.modules.executing.l3.fii_gb200_milestone.t0_interactive import (
    fetch_interactive_e_supplement,
)
from apps.copilot.modules.executing.l3.fii_gb200_milestone.t0_proxies import collect_shadow_proxies

logger = logging.getLogger(__name__)


def _block(code: str, reason: str) -> dict[str, Any]:
    return {"probe_key": PROBE_KEY, "ok": False, "blocker": f"[{code}] {reason}", "payload": None}


def _ok(payload: dict[str, Any], source: str) -> dict[str, Any]:
    return {"probe_key": PROBE_KEY, "ok": True, "blocker": None, "payload": payload, "source": source}


def _infer_doc_type(
    *,
    announcement_title: str,
    ir_qa: str,
    interactive: str,
) -> str:
    """T0 doc_type · earnings_transcript | cninfo_announcement。"""
    title = announcement_title or ""
    if re.search(r"业绩说明会|投资者关系|活动记录|说明会实录|电话会议", title):
        return "earnings_transcript"
    if len((ir_qa or "").strip()) >= 200:
        return "earnings_transcript"
    if len((interactive or "").strip()) >= 120:
        return "cninfo_announcement"
    return "cninfo_announcement"


def _build_event_raw_text(
    *,
    announcement: str,
    ir_qa: str,
    interactive: str,
) -> str:
    parts = [announcement.strip(), ir_qa.strip(), interactive.strip()]
    return "\n".join(p for p in parts if p)


def collect_fii_gb200_milestone_t0(
    symbol: str = "601138",
    *,
    prior_lifecycle_stage: str | None = None,
    prior_signal_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """巨潮公告/业绩会实录+互动易 · 侧翼备料影子 · DeepSea T0 传感器层。"""
    sym = symbol.zfill(6)[-6:]
    event = fetch_gb200_official_event(sym)
    qa = fetch_investor_relations_qa(sym)
    ir_text = str(qa.get("investor_relations_qa") or "") if qa.get("ok") else ""

    if not event.get("ok"):
        if qa.get("ok") and len(ir_text.strip()) >= 80:
            event = {
                "ok": True,
                "source": "cninfo:ir_transcript_primary",
                "announcement_title": qa.get("report_title"),
                "official_announcement_text": ir_text[:8000],
                "published_date": qa.get("published_date"),
                "adjunct_url": None,
                "match_score": qa.get("score"),
                "pdf_chars": qa.get("qa_full_chars"),
                "analysis_window": qa.get("analysis_window") or event_window_meta(),
            }
        else:
            return _block("T0", str(event.get("blocker") or qa.get("blocker") or "公告采集失败"))

    interact = fetch_interactive_e_supplement(sym)
    interact_text = str(interact.get("interactive_e_text") or "") if interact.get("ok") else ""

    try:
        shadows = collect_shadow_proxies(sym)
    except Exception as exc:  # noqa: BLE001
        logger.warning("影子指标采集异常: %s", exc)
        shadows = {"proxy_confidence": "low", "active_proxy_count": 0}

    announcement_text = str(event.get("official_announcement_text") or "")
    event_raw = _build_event_raw_text(
        announcement=announcement_text,
        ir_qa=ir_text,
        interactive=interact_text,
    )

    adjunct = str(event.get("adjunct_url") or "")
    doc_id = f"doc_{sym}_cninfo_{event.get('published_date', 'unknown')}"
    if adjunct:
        doc_id = f"doc_{sym}_{adjunct.split('/')[-1].replace('.pdf', '')[:48]}"

    doc_type = _infer_doc_type(
        announcement_title=str(event.get("announcement_title") or ""),
        ir_qa=ir_text,
        interactive=interact_text,
    )

    payload: dict[str, Any] = {
        "symbol": sym,
        "doc_id": doc_id,
        "doc_type": doc_type,
        "parsed_markdown_uri": f"parsed/{doc_id}.md",
        "temporal_benchmark": {
            "nvidia_blackwell_ga_date": upstream_bottleneck_date(),
        },
        "event_raw_text": event_raw,
        "announcement_title": event.get("announcement_title"),
        "official_announcement_text": announcement_text,
        "published_date": event.get("published_date"),
        "investor_relations_qa": ir_text,
        "interactive_e_text": interact_text,
        "qa_published_date": qa.get("published_date") if qa.get("ok") else None,
        "prior_lifecycle_stage": prior_lifecycle_stage,
        "prior_signal_snapshot": prior_signal_snapshot,
        "event_window": event.get("analysis_window") or event_window_meta(),
        "baseline_window": baseline_window_meta(),
        "analysis_window": event_window_meta(),
        "npi_state_dictionary": {
            k: {
                "rank": v["rank"],
                "label_zh": v["label_zh"],
                "trade_posture": v.get("trade_posture"),
                "terms": list(v["terms"]),
            }
            for k, v in NPI_STATE_DICTIONARY.items()
        },
        "product_lifecycle_dictionary": {
            k: {"rank": v["rank"], "label_zh": v["label_zh"], "terms": list(v["terms"])}
            for k, v in NPI_STATE_DICTIONARY.items()
        },
        "expected_segments": list(EXPECTED_SEGMENTS),
        "upstream_bottleneck_date": upstream_bottleneck_date(),
        "proxy_spike_threshold": PROXY_SPIKE_THRESHOLD,
        "shadow_proxies": shadows,
        "event_match_score": event.get("match_score"),
        "pdf_chars": event.get("pdf_chars"),
        "adjunct_url": event.get("adjunct_url"),
        "qa_doc_title": qa.get("report_title") if qa.get("ok") else None,
        "sensor_cadence": {
            "event_text": "daily",
            "chroma_revenue": "monthly",
            "raw_materials": "quarterly",
            "baseline_months": BASELINE_LOOKBACK_MONTHS,
            "event_months": EVENT_LOOKBACK_MONTHS,
        },
    }
    src = str(event.get("source") or "cninfo")
    if qa.get("ok"):
        src = f"{src}+{qa.get('source', 'ir_qa')}"
    if interact.get("ok"):
        src = f"{src}+interactive_e"
    src = f"{src}+shadow({shadows.get('active_proxy_count', 0)})"
    return _ok(payload, src)
