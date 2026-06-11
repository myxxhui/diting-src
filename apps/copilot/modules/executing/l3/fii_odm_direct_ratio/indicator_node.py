"""fii_odm_direct_ratio T1 指标节点。

[Ref: 28_ §4.1]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.card_strategy import build_card_strategy
from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.t1_contract import build_t1_contract
from apps.copilot.modules.executing.probe_labels import probe_indicator_name


def build_fii_odm_direct_ratio_node(
    t0_payload: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    contract = build_t1_contract(t0_payload)
    ratio = contract["odm_ratio_pct"]
    rev = contract["odm_revenue_cny"]
    lo, hi = float(ratio["lo"]), float(ratio["hi"])
    mid_raw = ratio.get("mid")
    lo_cny, hi_cny = int(rev["lo"]), int(rev["hi"])
    card_strategy = build_card_strategy(t0_payload, contract)
    sem_sig = contract.get("semantic_signal") if isinstance(contract.get("semantic_signal"), dict) else {}
    solver = contract.get("solver") if isinstance(contract.get("solver"), dict) else {}
    method = str(solver.get("method") or "")
    label = str(sem_sig.get("label") or "—")
    yoy = t0_payload.get("total_cloud_yoy_pct")
    yoy_s = f"YoY {float(yoy):.0f}%" if yoy is not None else ""
    cloud_b = int(t0_payload["total_cloud_revenue_cny"]) / 1e8

    sem = t0_payload.get("semantic_evidence_layer") if isinstance(
        t0_payload.get("semantic_evidence_layer"), dict
    ) else {}
    n_ev = len(sem.get("evidence_quotes") or [])

    if mid_raw is not None:
        mid = float(mid_raw)
        value = f"{mid:.1f}%"
        value_detail = f"{label} · {lo:.1f}–{hi:.1f}% · 云 {cloud_b:.0f}亿"
    elif method == "semantic_evidence_only":
        value = label
        value_detail = f"云 {cloud_b:.0f}亿 · {yoy_s} · {n_ev}条语义证据"
    else:
        value = label
        value_detail = f"云 {cloud_b:.0f}亿 · {yoy_s}"

    calc = (
        f"R_cloud={int(t0_payload['total_cloud_revenue_cny']):,} CNY · "
        f"semantic={method} · llm_tag={contract.get('llm_tag', '—')}"
    )

    return {
        "indicator_name": probe_indicator_name("fii_odm_direct_ratio"),
        "value": value,
        "value_detail": value_detail,
        "fact_statement": contract["fact_statement"],
        "calculation_logic": calc,
        "source": source,
        "t1_json": contract,
        "raw_metrics": {
            "report_period": t0_payload.get("report_period"),
            "report_year": t0_payload.get("report_year"),
            "report_quarter": t0_payload.get("report_quarter"),
            "total_cloud_revenue_cny": t0_payload.get("total_cloud_revenue_cny"),
            "total_cloud_yoy_pct": t0_payload.get("total_cloud_yoy_pct"),
            "qa_raw_transcript": (t0_payload.get("qa_raw_transcript") or "")[:2000],
            "semantic_evidence_layer": t0_payload.get("semantic_evidence_layer"),
            "is_breakdown_published": t0_payload.get("is_breakdown_published"),
            "t0_payload": t0_payload,
            "card_strategy": card_strategy,
        },
    }
