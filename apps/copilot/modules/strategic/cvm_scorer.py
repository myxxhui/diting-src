"""CVM 6+1 T1 规则评分（v2.0 · C1-C4 独立 band · C7 四分类引擎）。

[Ref: 33_ §4.6 · 34_ §3.7 · 32_ §2.4.4]
"""
from __future__ import annotations

from typing import Any, Optional


# ── 角色映射表 ──
# (role_suggested, anchor_path, pool_default, c7_category)
# c7_category: monopoly / leader / max_value / sentinel
_ROLE_MAP: dict[str, tuple[str, str, bool, str]] = {
    "硬件巨头":         ("monopoly",       "structure", True,  "monopoly"),
    "光模块龙头":       ("leader",          "structure", True,  "leader"),
    "卡脖子新贵":       ("max_value",       "growth",    True,  "max_value"),
    "算力精算师":       ("leader",          "growth",    True,  "leader"),
    "算力网络可视化":   ("representative",  "structure", False, "max_value"),
    "办公 AI 领航者":   ("leader",          "profit",    True,  "leader"),
    "合规与私有化先锋": ("leader",          "profit",    True,  "leader"),
    "工业 Agent 中枢":  ("leader",          "growth",    True,  "leader"),
    "多体协同 Agent":   ("representative",  "growth",    False, "max_value"),
}

# ── C7 四分类哨兵引擎 ──
# 每个分类定义：pass 条件 + 触发原因 + anchor_strength
_C7_CLASSES: dict[str, dict[str, Any]] = {
    "monopoly": {
        "pass": True,
        "category": "monopoly",
        "label": "真龙头",
        "description": "卡脖子深度高 + 份额垄断 + 不可替代",
        "anchor_strength": "high",
        "triggers": [],
    },
    "leader": {
        "pass": True,
        "category": "leader",
        "label": "行业领先",
        "description": "份额领先但非垄断，技术/规模有壁垒",
        "anchor_strength": "mid_high",
        "triggers": [],
    },
    "max_value": {
        "pass": True,
        "category": "max_value",
        "label": "高价值新贵",
        "description": "技术/利润锚点突出但规模小·需跟踪",
        "anchor_strength": "mid",
        "triggers": ["small_cap_warning"],
    },
    "sentinel": {
        "pass": False,
        "category": "sentinel",
        "label": "伪龙头哨兵",
        "description": "叙事龙头/小龙头/路线弃子/代工无锚",
        "anchor_strength": "none",
        "triggers": [
            "narrative_only_no_revenue",
            "no_moat_evidence",
            "government_subsidy_dependent",
            "representative_only",
        ],
    },
}


def _band_from_role(role_tag: str) -> str:
    if "龙头" in role_tag or "巨头" in role_tag:
        return "high"
    if "新贵" in role_tag or "精算" in role_tag:
        return "mid_high"
    if "对照" in role_tag or "representative" in role_tag.lower():
        return "acceptable"
    return "mid_high"


# ── C1-C4 独立 band 函数 ──

def _band_c1_profit_pool(role_tag: str, c7_category: str) -> str:
    """利润池占有：卡脖子/垄断型 → high；跟随型 → mid 以下。"""
    if c7_category == "monopoly":
        return "high"
    if "寡头" in role_tag or "巨头" in role_tag or "龙头" in role_tag:
        return "high"
    if "新贵" in role_tag or "精算" in role_tag:
        return "mid_high"
    return "mid"


def _band_c2_chokepoint(role_tag: str, c7_category: str) -> str:
    """卡脖子深度：替换成本+认证稀缺度。"""
    if c7_category == "monopoly":
        return "high"
    if "卡脖子" in role_tag or "替代" in role_tag:
        return "high"
    if c7_category == "leader" or "龙头" in role_tag:
        return "mid_high"
    if c7_category == "max_value":
        return "mid_high"
    return "mid"


def _band_c3_value_elasticity(role_tag: str, c7_category: str) -> str:
    """价值量弹性：放量时价值量是否同步放大。"""
    if c7_category in ("monopoly", "leader") and "制造" not in role_tag:
        return "high"
    if "代工" in role_tag or "制造" in role_tag:
        return "mid"
    if c7_category == "max_value":
        return "mid_high"
    return "mid"


def _band_c4_structure_dominance(role_tag: str, c7_category: str) -> str:
    """结构主导权：份额+客户锁+标准话语权。"""
    if c7_category == "monopoly":
        return "high"
    if "龙头" in role_tag or "巨头" in role_tag:
        return "high"
    if "先锋" in role_tag or "中枢" in role_tag:
        return "mid_high"
    return "mid"


# ── C7 四分类判定 ──

def _classify_c7(role_tag: str, role_suggested: str) -> dict[str, Any]:
    """C7 四分类规则引擎。"""
    tag = (role_tag or "").strip()

    # sentinel 触发条件
    if role_suggested == "representative":
        cls = _C7_CLASSES["sentinel"]
        cls["triggers"] = ["representative_only"]
        return cls

    # 缺失 role_tag 或 role_tag 为空 → sentinel
    if not tag:
        cls = _C7_CLASSES["sentinel"]
        cls["triggers"] = ["narrative_only_no_revenue"]
        return cls

    # 基于 ROLE_MAP 获取预置类别
    _, _, _, c7_cat = _ROLE_MAP.get(tag, ("leader", "structure", True, "sentinel"))
    if c7_cat == "sentinel":
        return _C7_CLASSES["sentinel"]

    return _C7_CLASSES.get(c7_cat, _C7_CLASSES["leader"])


def score_symbol(
    symbol: str,
    *,
    role_tag: Optional[str] = None,
    niche_id: str = "default",
) -> dict[str, Any]:
    """对单 symbol 产出 CVM 矩阵行（T1 · provisional 直至 T2 语义增强或财务 T0 就绪）。

    v2.0 改进：
    - C1-C4 四维独立 band，不再共用同一 band
    - C7 四分类引擎（monopoly/leader/max_value/sentinel）
    - 兼容现有调用方（返回结构不变，scores 结构保持）
    """
    tag = (role_tag or "").strip()
    role_suggested, anchor_path, pool_default, _ = _ROLE_MAP.get(
        tag, ("leader", "structure", True, "sentinel")
    )

    # C7 四分类
    c7_result = _classify_c7(tag, role_suggested)
    c7_pass = c7_result["pass"]
    c7_category = c7_result["category"]

    # C1-C4 独立 band
    b1 = _band_c1_profit_pool(tag, c7_category)
    b2 = _band_c2_chokepoint(tag, c7_category)
    b3 = _band_c3_value_elasticity(tag, c7_category)
    b4 = _band_c4_structure_dominance(tag, c7_category)

    scores = {
        "c1": {"band": b1, "trend": "flat", "evidence_refs": []},
        "c2": {"band": b2, "needs_semantic_review": b2 in ("mid_high", "mid")},
        "c3": {"band": b3},
        "c4": {"band": b4},
        "c5": {"bypass_risk": "low" if c7_pass else "mid"},
        "c6": {"band": _band_from_role(tag)},
        "c7": {
            "pass": c7_pass,
            "category": c7_category,
            "label": c7_result.get("label", ""),
            "anchor_strength": c7_result.get("anchor_strength", "none"),
            "triggers": c7_result.get("triggers", []),
        },
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
    """批量评分 T1 行。"""
    rows = []
    for p in peers:
        sym = str(p.get("symbol") or "").strip()
        if not sym:
            continue
        row = score_symbol(sym, role_tag=p.get("role_tag"), niche_id=niche_id)
        rows.append(row)
    return rows
