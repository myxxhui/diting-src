"""T1 生命周期/状态机辅助函数。

[Ref: 28_ §2.2 fii_gb200_milestone]
"""
from __future__ import annotations

from datetime import date
from typing import Any

from apps.copilot.modules.executing.l3.fii_gb200_milestone.constants import (
    FUZZY_PR_TERMS,
    LIFECYCLE_ORDER,
    PRODUCT_LIFECYCLE_DICTIONARY,
    PRODUCT_SEGMENT_PATTERNS,
)


def _combined_text(t0: dict[str, Any]) -> str:
    parts = [
        str(t0.get("event_raw_text") or ""),
        str(t0.get("official_announcement_text") or ""),
        str(t0.get("investor_relations_qa") or ""),
        str(t0.get("interactive_e_text") or ""),
        str(t0.get("announcement_title") or ""),
    ]
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        s = p.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return "\n".join(out)


def map_product_segment(text: str) -> str | None:
    for pat, label in PRODUCT_SEGMENT_PATTERNS:
        if pat.search(text):
            return label
    return None


def detect_lifecycle_stage(text: str) -> tuple[str | None, str | None, list[str]]:
    best_key: str | None = None
    best_rank = 0
    matched: list[str] = []
    for key, meta in PRODUCT_LIFECYCLE_DICTIONARY.items():
        for term in meta["terms"]:
            if term in text:
                matched.append(term)
                rank = int(meta["rank"])
                if rank > best_rank:
                    best_rank = rank
                    best_key = key
    if not best_key:
        return None, None, []
    return best_key, str(PRODUCT_LIFECYCLE_DICTIONARY[best_key]["label_zh"]), matched


def matched_terms_from_lifecycle(text: str) -> list[str]:
    _, _, terms = detect_lifecycle_stage(text)
    return terms


def extract_fuzzy_terms(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    idx = 1
    for term in FUZZY_PR_TERMS:
        if term in text:
            out[f"term_{idx}"] = term
            idx += 1
    return out


def _parse_event_date(t0: dict[str, Any]) -> date | None:
    raw = str(t0.get("published_date") or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def check_temporal_paradox(
    event_date: date | None,
    upstream_bottleneck: str,
    stage_key: str | None,
) -> dict[str, Any]:
    try:
        floor = date.fromisoformat(str(upstream_bottleneck)[:10])
    except ValueError:
        return {"paradox": False, "note": "upstream_bottleneck_date 无效·跳过拦截"}
    if stage_key not in ("MP", "PVT") or event_date is None:
        return {"paradox": False, "upstream_floor": floor.isoformat()}
    paradox = event_date < floor
    return {
        "paradox": paradox,
        "event_date": event_date.isoformat(),
        "upstream_floor": floor.isoformat(),
        "note": "宣告量产早于 Blackwell 批量发货窗口·公关幻觉拦截" if paradox else "时序一致",
    }


def detect_state_transition(prior: str | None, current: str | None) -> str | None:
    if not current:
        return None
    if not prior:
        return f"→{current}"
    if prior == current:
        return f"{prior}(hold)"
    try:
        pi = LIFECYCLE_ORDER.index(prior)
        ci = LIFECYCLE_ORDER.index(current)
    except ValueError:
        return f"{prior}→{current}"
    if ci > pi:
        return f"{prior}→{current}"
    if ci < pi:
        return f"{prior}↓{current}"
    return f"{prior}(hold)"
