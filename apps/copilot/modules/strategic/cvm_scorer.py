"""CVM 6+1 T1 规则评分（启动期 · 无 LLM C7）。

[Ref: 33_ §4.6 · 34_ §3.7 · 32_ §2.4.4]
"""
from __future__ import annotations

from typing import Any, Optional


_ROLE_MAP = {
    "硬件巨头": ("monopoly", "structure", True),
    "光模块龙头": ("leader", "structure", True),
    "卡脖子新贵": ("max_value", "growth", True),
    "算力精算师": ("leader", "growth", True),
    "算力网络可视化": ("representative", "structure", False),
    "办公 AI 领航者": ("leader", "profit", True),
    "合规与私有化先锋": ("leader", "profit", True),
    "工业 Agent 中枢": ("leader", "growth", True),
    "多体协同 Agent": ("representative", "growth", False),
}


def _band_from_role(role_tag: str) -> str:
    if "龙头" in role_tag or "巨头" in role_tag:
        return "high"
    if "新贵" in role_tag or "精算" in role_tag:
        return "mid_high"
    if "对照" in role_tag or "representative" in role_tag.lower():
        return "acceptable"
    return "mid_high"


def score_symbol(
    symbol: str,
    *,
    role_tag: Optional[str] = None,
    niche_id: str = "default",
) -> dict[str, Any]:
    """对单 symbol 产出 CVM 矩阵行（T1 · provisional 直至财务 T0 就绪）。"""
    tag = (role_tag or "").strip()
    role_suggested, anchor_path, pool_default = _ROLE_MAP.get(
        tag, ("leader", "structure", True)
    )
    band = _band_from_role(tag or "未知")
    c7_pass = role_suggested != "representative" and "对照" not in tag
    if not tag:
        c7_pass = True

    scores = {
        "c1": {"band": band, "trend": "flat", "evidence_refs": []},
        "c2": {"band": band, "needs_semantic_review": band == "mid_high"},
        "c3": {"band": band},
        "c4": {"band": band},
        "c5": {"bypass_risk": "low" if c7_pass else "mid"},
        "c6": {"band": band},
        "c7": {"pass": c7_pass, "triggers": [] if c7_pass else ["representative_only"]},
    }
    pool_eligible = pool_default and c7_pass and role_suggested != "representative"
    return {
        "symbol": symbol,
        "niche_id": niche_id,
        "scores": scores,
        "anchor_path": anchor_path,
        "role_suggested": role_suggested,
        "pool_eligible": pool_eligible,
        "dispatch_priority": 1 if role_suggested in ("monopoly", "max_value") else 2,
        "provisional": True,
        "human_confirmed": False,
        "role_tag_source": tag or None,
    }


def score_peer_set(
    peers: list[dict[str, Any]],
    *,
    niche_id: str = "default",
) -> list[dict[str, Any]]:
    rows = []
    for p in peers:
        sym = str(p.get("symbol") or "").strip()
        if not sym:
            continue
        row = score_symbol(sym, role_tag=p.get("role_tag"), niche_id=niche_id)
        rows.append(row)
    return rows
