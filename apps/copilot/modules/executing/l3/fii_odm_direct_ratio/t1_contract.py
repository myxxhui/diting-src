"""T1 防置换契约 JSON（喂 T2 / 卡片）。

[Ref: 28_ §2.2 fii_odm_direct_ratio · Contract Layer]
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.t1_solver import (
    extract_qa_excerpt_summary,
    solve_odm_direct_ratio,
)

_CST = timezone(timedelta(hours=8))


def build_t1_contract(t0_payload: dict[str, Any]) -> dict[str, Any]:
    solved = solve_odm_direct_ratio(t0_payload)
    ratio = solved["odm_ratio_pct"]
    rev = solved["odm_revenue_cny"]
    period = str(t0_payload.get("report_period") or "")
    total = int(t0_payload["total_cloud_revenue_cny"])
    yoy = t0_payload.get("total_cloud_yoy_pct")
    yoy_s = f"{float(yoy):.1f}%" if yoy is not None else "—"
    lo_pct = ratio["lo"]
    hi_pct = ratio["hi"]
    mid_pct = ratio.get("mid")
    lo_cny = int(rev["lo"])
    hi_cny = int(rev["hi"])
    sem = t0_payload.get("semantic_evidence_layer") if isinstance(
        t0_payload.get("semantic_evidence_layer"), dict
    ) else {}
    sem_sig = solved.get("semantic_signal") if isinstance(solved.get("semantic_signal"), dict) else {}
    solver = solved.get("solver") or {}
    method = str(solver.get("method") or "")
    llm_tag = sem.get("llm_tag") or solver.get("llm_tag") or "—"
    evidence = sem.get("evidence_quotes") if isinstance(sem.get("evidence_quotes"), list) else []
    n_ev = len(evidence)

    missing: dict[str, str] = {}
    if not t0_payload.get("is_breakdown_published"):
        missing["exact_odm_revenue_cny_in_report"] = "MISSING_IN_SOURCE"
    if method in ("insufficient_semantic_evidence",):
        missing["semantic_evidence"] = "BLOCKED_NO_IR_OR_DEEPSEEK"

    if method == "semantic_evidence_only":
        ratio_line = (
            f"语义评估 {sem_sig.get('label', '—')} · {n_ev} 条一手原句 · "
            f"云营收 {total/1e8:.1f} 亿(YoY {yoy_s}) · ODM占云业务占比未披露"
        )
    elif method == "semantic_inferred_ratio" and mid_pct is not None:
        ratio_line = (
            f"语义推断 ODM占云业务 {lo_pct:.1f}–{hi_pct:.1f}%（{llm_tag}）· "
            f"隐含 {lo_cny/1e8:.1f}–{hi_cny/1e8:.1f} 亿"
        )
    elif method == "published_breakdown":
        ratio_line = f"财报披露 ODM占比 {mid_pct:.1f}%"
    elif mid_pct is not None:
        ratio_line = f"ODM占比 {lo_pct:.1f}–{hi_pct:.1f}%"
    else:
        ratio_line = f"云营收硬锚 {total/1e8:.1f} 亿 · 占比未推断"

    verdict = str(sem.get("overall_verdict_zh") or solver.get("note") or "")[:200]
    fact = (
        f"【语义证据层】工业富联{period} · {ratio_line}。"
        f"llm_tag={llm_tag} · IR实录：{extract_qa_excerpt_summary(str(t0_payload.get('qa_raw_transcript') or ''), max_len=60)}。"
        f"{verdict}"
    )

    return {
        "indicator_id": "fii_odm_direct_ratio",
        "audit_timestamp": datetime.now(_CST).isoformat(),
        "period": period,
        "llm_tag": llm_tag,
        "semantic_evidence_layer": sem,
        "semantic_signal": sem_sig,
        "macro_truth_from_T0": {
            "total_cloud_revenue_cny": total,
            "total_cloud_yoy_pct": yoy_s,
        },
        "segment_inventory_from_T0": {
            "expected_segments": [
                "ODM直供业务 (CSP Direct, 北美大厂为主)",
                "传统OEM业务 (Brand Servers, 戴尔/惠普等为主)",
                "其他及边缘网络产品",
            ],
            "is_breakdown_published": bool(t0_payload.get("is_breakdown_published")),
        },
        "anti_substitution_matrix": solved.get("anti_substitution_matrix"),
        "implied_value_range": solved["anti_substitution_matrix"]["implied_value_range"],
        "odm_ratio_pct": ratio,
        "odm_revenue_cny": rev,
        "missing_data_flags": missing,
        "physical_fact_contract": fact,
        "fact_statement": fact,
        "solver": solver,
    }
