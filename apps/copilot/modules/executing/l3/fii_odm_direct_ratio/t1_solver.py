"""T1 · ODM 直供：财报硬锚 + 语义证据层。

[Ref: 28_ §2.2 fii_odm_direct_ratio · §2.8 DeepSeek]
"""
from __future__ import annotations

import re
from typing import Any

from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.t1_semantic import (
    growth_signal_display,
)


def _semantic_layer(t0: dict[str, Any]) -> dict[str, Any]:
    sem = t0.get("semantic_evidence_layer")
    return sem if isinstance(sem, dict) else {}


def solve_odm_direct_ratio(t0: dict[str, Any]) -> dict[str, Any]:
    """云营收硬锚 + DeepSeek 语义证据；仅财报直接披露时用精确占比。"""
    total = float(t0["total_cloud_revenue_cny"])
    sem = _semantic_layer(t0)
    assessment = sem.get("semantic_assessment") if isinstance(sem.get("semantic_assessment"), dict) else {}
    inferred = (
        sem.get("inferred_odm_share_of_cloud_pct")
        if isinstance(sem.get("inferred_odm_share_of_cloud_pct"), dict)
        else {}
    )
    growth_signal = str(assessment.get("odm_csp_growth_signal") or "unclear")
    status, signal_label = growth_signal_display(growth_signal)
    evidence = sem.get("evidence_quotes") if isinstance(sem.get("evidence_quotes"), list) else []
    confidence = str(inferred.get("confidence") or "none")

    published = t0.get("odm_direct_ratio_published_pct")
    if published is not None and t0.get("is_breakdown_published"):
        ratio = float(published)
        lo_cny = int(total * ratio / 100)
        return {
            "odm_ratio_pct": {"lo": ratio, "mid": ratio, "hi": ratio},
            "odm_revenue_cny": {"lo": lo_cny, "mid": lo_cny, "hi": lo_cny},
            "semantic_signal": {"status": status, "label": signal_label, "growth_signal": growth_signal},
            "anti_substitution_matrix": {
                "target_segment": "ODM直供业务 (CSP Direct)",
                "evidence_quotes": evidence[:8],
                "semantic_assessment": assessment,
                "implied_value_range": {
                    "calculated_lower_bound_ratio": f"{ratio:.1f}%",
                    "calculated_lower_bound_cny": lo_cny,
                    "calculated_upper_bound_cny": lo_cny,
                    "calculation_source": "财报直接披露 ODM 占比",
                },
            },
            "solver": {"method": "published_breakdown", "llm_tag": sem.get("llm_tag")},
        }

    # 语义推断占比（仅 medium/high 且给了 lo/hi）
    lo_inf = inferred.get("lo")
    hi_inf = inferred.get("hi")
    point_inf = inferred.get("point")
    if confidence in ("high", "medium") and lo_inf is not None and hi_inf is not None:
        lo_p = float(lo_inf)
        hi_p = float(hi_inf)
        mid_p = float(point_inf) if point_inf is not None else (lo_p + hi_p) / 2
        lo_cny = int(total * lo_p / 100)
        hi_cny = int(total * hi_p / 100)
        mid_cny = int(total * mid_p / 100)
        return {
            "odm_ratio_pct": {"lo": lo_p, "mid": mid_p, "hi": hi_p},
            "odm_revenue_cny": {"lo": lo_cny, "mid": mid_cny, "hi": hi_cny},
            "semantic_signal": {"status": status, "label": signal_label, "growth_signal": growth_signal},
            "anti_substitution_matrix": {
                "target_segment": "ODM直供业务 (CSP Direct)",
                "evidence_quotes": evidence[:8],
                "semantic_assessment": assessment,
                "inferred_odm_share_of_cloud_pct": inferred,
                "implied_value_range": {
                    "calculated_lower_bound_ratio": f"{lo_p:.1f}%",
                    "calculated_upper_bound_cny": lo_cny,
                    "calculated_upper_bound_cny": hi_cny,
                    "calculation_source": f"DeepSeek语义推断 confidence={confidence}",
                },
            },
            "solver": {
                "method": "semantic_inferred_ratio",
                "llm_tag": sem.get("llm_tag"),
                "note": inferred.get("method_zh") or "",
            },
        }

    # 语义证据层：有证据 → 信号档位；占比不硬编
    if evidence and growth_signal in ("strong_up", "moderate_up", "flat"):
        n_strong = sum(1 for e in evidence if isinstance(e, dict) and e.get("strength") == "strong")
        return {
            "odm_ratio_pct": {"lo": 0.0, "mid": None, "hi": 100.0},
            "odm_revenue_cny": {"lo": 0, "mid": None, "hi": int(total)},
            "semantic_signal": {
                "status": status,
                "label": signal_label,
                "growth_signal": growth_signal,
                "evidence_count": len(evidence),
                "strong_count": n_strong,
            },
            "anti_substitution_matrix": {
                "target_segment": "ODM直供业务 (CSP Direct)",
                "evidence_quotes": evidence[:8],
                "semantic_assessment": assessment,
                "inferred_odm_share_of_cloud_pct": inferred,
                "implied_value_range": {
                    "calculated_lower_bound_ratio": "—",
                    "calculation_source": "semantic_evidence_only · 无财报ODM占比披露",
                },
            },
            "solver": {
                "method": "semantic_evidence_only",
                "llm_tag": sem.get("llm_tag"),
                "note": assessment.get("thesis_rationale_zh") or sem.get("overall_verdict_zh") or "",
            },
        }

    return {
        "odm_ratio_pct": {"lo": 0.0, "mid": None, "hi": 100.0},
        "odm_revenue_cny": {"lo": 0, "mid": None, "hi": int(total)},
        "semantic_signal": {"status": "yellow", "label": "语料不足", "growth_signal": "unclear"},
        "anti_substitution_matrix": {
            "target_segment": "ODM直供业务 (CSP Direct)",
            "evidence_quotes": evidence[:8],
            "semantic_assessment": assessment,
            "implied_value_range": {"calculation_source": "insufficient_semantic_evidence"},
        },
        "solver": {
            "method": "insufficient_semantic_evidence",
            "llm_tag": sem.get("llm_tag"),
            "note": "缺 IR 记录表或 DeepSeek 证据",
        },
    }


def extract_qa_excerpt_summary(qa: str, *, max_len: int = 120) -> str:
    qa = re.sub(r"\s+", " ", qa).strip()
    if not qa:
        return "无 IR 实录"
    return qa[:max_len] + ("…" if len(qa) > max_len else "")
