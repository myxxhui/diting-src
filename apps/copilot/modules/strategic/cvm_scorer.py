"""CVM 6+1 T1 规则评分（v2.1 · C1-C4 独立 band · C7 四分类引擎 · 进池门槛 + 不可替代性汇总）。

[Ref: 33_ §4.6 · 34_ §3.7 · 32_ §2.4.4 · 32_ §2.4.8（Z1.5 消费契约）]
"""
from __future__ import annotations

from typing import Any, Optional


# ── band 等级排序（用于进池门槛 min 校验）──
_BAND_ORDER: dict[str, int] = {
    "low": 0,
    "acceptable": 1,
    "mid": 2,
    "mid_high": 3,
    "high": 4,
}
# 进池门槛：C1-C4 最低 acceptable 档（≥ acceptable）
_POOL_MIN_BAND = "acceptable"
_POOL_MIN_ORD = _BAND_ORDER.get(_POOL_MIN_BAND, 1)
# C5 bypass_risk 上限：不可为 high
_C5_BYPASS_BLOCK = "high"


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


# ── 进池门槛校验（32_ §2.4.4 · gates.yaml z0_cvm）──

def _check_pool_gate(scores: dict[str, Any]) -> tuple[bool, list[str]]:
    """校验 CVM 进池必要条件（C7=pass + min(C1,C2,C3,C4)≥acceptable + C5≠bypass_high + 至少一路径）。

    返回 (passed, fail_reasons)。
    """
    reasons: list[str] = []

    # 条件 1：C7 = pass
    c7 = scores.get("c7") or {}
    if not c7.get("pass", False):
        reasons.append("c7_not_pass")

    # 条件 2：min(C1,C2,C3,C4) ≥ acceptable
    for dim in ("c1", "c2", "c3", "c4"):
        band = (scores.get(dim) or {}).get("band", "low")
        if _BAND_ORDER.get(band, 0) < _POOL_MIN_ORD:
            reasons.append(f"{dim}_below_acceptable({band})")

    # 条件 3：C5 ≠ bypass_high
    c5_risk = (scores.get("c5") or {}).get("bypass_risk", "low")
    if c5_risk == _C5_BYPASS_BLOCK:
        reasons.append("c5_bypass_high")

    # 条件 4：至少一路径（A 利润锚 / B 结构锚 / C 成长锚）
    path_a = _BAND_ORDER.get((scores.get("c1") or {}).get("band", "low"), 0) >= _BAND_ORDER["high"]
    path_b = (
        _BAND_ORDER.get((scores.get("c2") or {}).get("band", "low"), 0) >= _BAND_ORDER["high"]
        and _BAND_ORDER.get((scores.get("c4") or {}).get("band", "low"), 0) >= _BAND_ORDER["mid_high"]
    )
    path_c = (
        _BAND_ORDER.get((scores.get("c3") or {}).get("band", "low"), 0) >= _BAND_ORDER["high"]
        and _BAND_ORDER.get((scores.get("c6") or {}).get("band", "low"), 0) >= _BAND_ORDER["mid_high"]
    )
    if not (path_a or path_b or path_c):
        reasons.append("no_anchor_path")

    return (len(reasons) == 0, reasons)


# ── 不可替代性汇总（供 Z1.5 Step3 护城河分析消费 · 段永平护城河哲学）──

_ANCHOR_STRENGTH_SCORE: dict[str, float] = {
    "high": 1.0,
    "mid_high": 0.75,
    "mid": 0.5,
    "none": 0.0,
}


def _calc_irreplaceability(scores: dict[str, Any]) -> dict[str, Any]:
    """汇总不可替代性：C2 卡脖子深度（0.4）+ C7 anchor_strength（0.35）+ C4 结构主导权（0.25）。

    段永平哲学映射：护城河 = 不可替代性 + 长期一致性。
    本字段供 Z1.5 Step3 护城河五力分析直接消费。
    """
    c2_band = (scores.get("c2") or {}).get("band", "low")
    c4_band = (scores.get("c4") or {}).get("band", "low")
    anchor = (scores.get("c7") or {}).get("anchor_strength", "none")

    c2_score = _BAND_ORDER.get(c2_band, 0) / 4.0
    c4_score = _BAND_ORDER.get(c4_band, 0) / 4.0
    anchor_score = _ANCHOR_STRENGTH_SCORE.get(anchor, 0.0)

    irreplaceability = round(c2_score * 0.40 + anchor_score * 0.35 + c4_score * 0.25, 3)

    if irreplaceability >= 0.75:
        level = "high"
    elif irreplaceability >= 0.5:
        level = "mid_high"
    elif irreplaceability >= 0.3:
        level = "mid"
    else:
        level = "low"

    return {
        "score": irreplaceability,
        "level": level,
        "components": {
            "c2_chokepoint": round(c2_score, 3),
            "c7_anchor_strength": round(anchor_score, 3),
            "c4_structure_dominance": round(c4_score, 3),
        },
        "duan_mapping": "护城河=不可替代性+长期一致性",
    }


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
        # 不可替代性汇总（供 Z1.5 Step3 护城河分析消费 · 段永平护城河哲学）
        "irreplaceability": _calc_irreplaceability({
            "c2": {"band": b2},
            "c4": {"band": b4},
            "c7": {"anchor_strength": c7_result.get("anchor_strength", "none")},
        }),
    }

    # 进池门槛校验（32_ §2.4.4 · C7=pass + min(C1-C4)≥acceptable + C5≠bypass_high + 至少一路径）
    gate_passed, gate_fail_reasons = _check_pool_gate(scores)
    pool_eligible = pool_default and gate_passed and role_suggested != "representative"
    return {
        "symbol": symbol,
        "niche_id": niche_id,
        "scores": scores,
        "anchor_path": anchor_path,
        "role_suggested": role_suggested,
        "pool_eligible": pool_eligible,
        "pool_gate": {
            "passed": gate_passed,
            "fail_reasons": gate_fail_reasons,
            "min_band_required": _POOL_MIN_BAND,
            "c5_bypass_block": _C5_BYPASS_BLOCK,
        },
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
