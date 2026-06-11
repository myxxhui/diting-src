"""T1 · GB200 量产节点 · DeepSea 纯语义状态机。

[Ref: 28_ §2.2 fii_gb200_milestone · deepsea_semantic_v1]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.executing.l3.fii_gb200_milestone.t1_semantic import (
    infer_gb200_milestone_semantic,
)


def solve_gb200_milestone(t0: dict[str, Any]) -> dict[str, Any]:
    """语义主路径；输出兼容 indicator_node / T2。"""
    sem = infer_gb200_milestone_semantic(t0)
    status = sem.get("signal_status")
    shadow = sem.get("shadow_validation") or {}
    prior = sem.get("prior_signal_status")
    transition = sem.get("state_transition")

    mp_reached = status == "MP" and not (sem.get("temporal_check") or {}).get("paradox")
    shadow_pass = bool(shadow.get("passed"))

    return {
        "deepsea_contract": sem,
        "mapped_segment": "GB200 NVL72/36 整机柜",
        "lifecycle_stage": status,
        "lifecycle_stage_label": sem.get("lifecycle_stage_label"),
        "prior_lifecycle_stage": prior,
        "state_transition": transition,
        "temporal_check": sem.get("temporal_check") or {},
        "evidence_quotes": sem.get("evidence_quotes") or [],
        "momentum_delta": sem.get("momentum_delta"),
        "momentum_rationale": sem.get("momentum_rationale"),
        "shadow_validation": shadow,
        "mp_starting_gun": mp_reached,
        "confirmed_breakthrough": mp_reached and shadow_pass and transition == "PVT→MP",
        "trade_trigger": mp_reached and shadow_pass,
        "missing_data_flags": {
            "exact_shipped_volume": "RESTRICTED_NDA_DATA",
            "exact_revenue_cny": "RESTRICTED_NDA_DATA",
        },
        "solver": {
            "method": "deepsea_semantic_v1",
            "llm_tag": sem.get("llm_tag"),
            "cache_group": sem.get("cache_group"),
            "note": "纯语义状态机+证据拼图；禁止假方程",
        },
    }


# 兼容旧单测 import
def build_shadow_proxy_validation_matrix(t0: dict[str, Any]) -> dict[str, Any]:
    from apps.copilot.modules.executing.l3.fii_gb200_milestone.t1_semantic import (
        build_shadow_validation,
    )
    from apps.copilot.modules.executing.l3.fii_gb200_milestone.t1_solver_lifecycle import (
        detect_lifecycle_stage,
        _combined_text,
    )

    text = _combined_text(t0)
    stage_key, _, _ = detect_lifecycle_stage(text)
    sv = build_shadow_validation(t0, signal_status=stage_key or "UNKNOWN")
    qoq = (t0.get("shadow_proxies") or {}).get("raw_materials_inventory") or {}
    raw_pass = sv.get("passed")
    return {
        "test_equipment_surge_check": {"status": "LEGACY", "note": "已迁移 shadow_validation"},
        "raw_material_hoarding_check": {
            "metric": "fii_raw_inventory QoQ > 30%",
            "actual": qoq.get("qoq_pct"),
            "status": "PASS" if raw_pass else "FAIL",
        },
        "dual_proxy_confirmed": raw_pass,
        "pass_count": 1 if raw_pass else 0,
        "shadow_validation": sv,
    }


def evaluate_proxy_shadow(t0: dict[str, Any]) -> dict[str, Any]:
    matrix = build_shadow_proxy_validation_matrix(t0)
    sv = matrix.get("shadow_validation") or {}
    return {
        "proxies": [],
        "active_count": matrix.get("pass_count", 0),
        "confidence": "high" if sv.get("passed") else "low",
        "shadow_proxy_validation_matrix": matrix,
        "physical_inference_zh": sv.get("note") or "",
    }


__all__ = [
    "build_shadow_proxy_validation_matrix",
    "evaluate_proxy_shadow",
    "solve_gb200_milestone",
]
