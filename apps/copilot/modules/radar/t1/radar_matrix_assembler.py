"""T1 fact_matrix 装配：17 算子 → 五域 feature_node。

[Ref: 27_ §3.7]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.radar.t1.fact_matrix_builder import build_fact_matrix_from_legacy
from apps.copilot.modules.radar.t1.operators.registry import ALL_OPERATORS, run_operator


def _empty_fact_matrix() -> dict[str, Any]:
    return {
        "global_and_meso": {},
        "ecosystem": {},
        "microstructure": {},
        "consensus": {},
        "risks_red_flags": {},
    }


def _has_p3_domains(t0_raw: dict[str, Any]) -> bool:
    return any(
        t0_raw.get(k)
        for k in ("macro", "ecosystem", "consensus", "risk", "micro")
    )


def assemble_fact_matrix(
    t0_raw: dict[str, Any],
    matrix: dict[str, Any],
    unavailable: list[str],
) -> tuple[dict[str, Any], list[str]]:
    """五域 fact_matrix：17 算子；缺 T0 则 unavailable（无 legacy 冒充）。"""
    if not _has_p3_domains(t0_raw):
        return build_fact_matrix_from_legacy(t0_raw, matrix, unavailable)

    fact_matrix = _empty_fact_matrix()
    unavailable_data = list(unavailable or [])

    for op_fn in ALL_OPERATORS:
        result = run_operator(op_fn, t0_raw)
        domain_block = fact_matrix.setdefault(result.domain, {})
        if result.node is not None:
            domain_block[result.key] = result.node
        elif result.skip_msg and result.skip_msg not in unavailable_data:
            unavailable_data.append(result.skip_msg)

    if matrix:
        fact_matrix["_legacy_matrix"] = matrix

    return fact_matrix, unavailable_data


def enrich_t1_payload(t0_raw: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    matrix = payload.get("matrix") or {}
    unavailable = list(payload.get("unavailable") or [])
    fact_matrix, unavailable_data = assemble_fact_matrix(t0_raw, matrix, unavailable)
    payload["fact_matrix"] = fact_matrix
    payload["unavailable_data"] = unavailable_data
    return payload
