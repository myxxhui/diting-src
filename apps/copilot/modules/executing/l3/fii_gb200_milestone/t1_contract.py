"""T1 契约 JSON · fii_gb200_milestone_deepsea_v1。

[Ref: 28_ §2.2 · DeepSea Contract Layer]
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from apps.copilot.modules.executing.l3.fii_gb200_milestone.constants import (
    CACHE_GROUP,
    CONTRACT_VERSION,
    INDICATOR_ID,
    event_window_meta,
)
from apps.copilot.modules.executing.l3.fii_gb200_milestone.t1_solver import solve_gb200_milestone

_CST = timezone(timedelta(hours=8))


def build_t1_contract(t0_payload: dict[str, Any]) -> dict[str, Any]:
    solved = solve_gb200_milestone(t0_payload)
    sem = solved.get("deepsea_contract") or {}
    fact = str(sem.get("fact_statement") or solved.get("fact_statement") or "").strip()

    return {
        "indicator_id": INDICATOR_ID,
        "audit_timestamp": datetime.now(_CST).isoformat(),
        "contract_version": CONTRACT_VERSION,
        "probe_key": sem.get("probe_key"),
        "symbol": sem.get("symbol") or t0_payload.get("symbol"),
        "signal_type": "semantic",
        "batch_id": CACHE_GROUP,
        "cache_group": CACHE_GROUP,
        "signal_status": sem.get("signal_status"),
        "value": None,
        "calculation_logic": None,
        "evidence_quotes": sem.get("evidence_quotes") or [],
        "fact_statement": fact,
        "physical_fact_contract": fact,
        "momentum_delta": sem.get("momentum_delta"),
        "momentum_rationale": sem.get("momentum_rationale"),
        "shadow_validation": sem.get("shadow_validation") or {},
        "doc_id": sem.get("doc_id") or t0_payload.get("doc_id"),
        "inferred_at": datetime.now(_CST).isoformat(),
        "source": sem.get("source") or "cninfo_announcement_feed · deepsea_semantic",
        "llm_tag": sem.get("llm_tag"),
        "event_window": t0_payload.get("event_window") or event_window_meta(),
        "state_machine": {
            "prior_stage": solved.get("prior_lifecycle_stage"),
            "current_stage": solved.get("lifecycle_stage"),
            "current_stage_label": solved.get("lifecycle_stage_label"),
            "transition": solved.get("state_transition"),
            "mp_starting_gun": solved.get("mp_starting_gun"),
            "confirmed_breakthrough": solved.get("confirmed_breakthrough"),
            "trade_trigger": solved.get("trade_trigger"),
        },
        "temporal_check": solved.get("temporal_check"),
        "missing_data_flags": solved.get("missing_data_flags") or {},
        "solver": solved.get("solver"),
        "deepsea_contract": sem,
    }
