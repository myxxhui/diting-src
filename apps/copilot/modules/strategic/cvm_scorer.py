"""CVM 6+1 T1 规则评分（v2.1 · C1-C4 独立 band · C7 四分类引擎 · 进池门槛 + 不可替代性汇总）。

[Ref: 33_ §4.6 · 34_ §3.7 · 32_ §2.4.4 · 32_ §2.4.8（Z1.5 消费契约）]
"""
from __future__ import annotations

from typing import Any, Optional

from apps.copilot.modules.strategic.duan_config import load_duan_node_gates, z0_cvm_gates


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

def _pool_min_band() -> str:
    return str(z0_cvm_gates().get("pool_min_band", _POOL_MIN_BAND))


def _c5_bypass_block() -> str:
    return str(z0_cvm_gates().get("c5_bypass_block", _C5_BYPASS_BLOCK))


def _check_pool_gate(
    scores: dict[str, Any],
    *,
    min_band: Optional[str] = None,
) -> tuple[bool, list[str]]:
    """校验 CVM 进池必要条件（C7=pass + min(C1,C2,C3,C4)≥min_band + C5≠bypass_high + 至少一路径）。

    [Ref: gates.yaml#z0_cvm]
    """
    reasons: list[str] = []
    min_ord = _BAND_ORDER.get(min_band or _pool_min_band(), _POOL_MIN_ORD)

    c7 = scores.get("c7") or {}
    if not c7.get("pass", False):
        reasons.append("c7_not_pass")

    for dim in ("c1", "c2", "c3", "c4"):
        band = (scores.get(dim) or {}).get("band", "low")
        if _BAND_ORDER.get(band, 0) < min_ord:
            reasons.append(f"{dim}_below_{min_band or _pool_min_band()}({band})")

    c5_risk = (scores.get("c5") or {}).get("bypass_risk", "low")
    if c5_risk == _c5_bypass_block():
        reasons.append("c5_bypass_high")

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


# ── Z0 段永平双闸 v4.2 完整版 ──
# [Ref: 32_ §2.4.9.a 节点环节闸 · §2.4.9.b 标的锚点闸 · duan_node_gates.yaml · gates.yaml]

_TIER_WEIGHT: dict[str, float] = {"核心": 1.0, "重要": 0.7, "配套": 0.4}

_NODE_VERDICT_PASS = ("pass", "✅好生意", 0.65, "环节 bypass 低且利润池锚定")
_NODE_VERDICT_REVIEW = ("review", "❓需深研", 0.35, "环节 bypass 中或时间跨度待确认")
_NODE_VERDICT_REJECT = ("reject", "❌看不懂", 0.0, "主链地位不足或 bypass 高")
_NODE_VERDICT_PROVISIONAL = ("provisional", "⚠️待环节T2", 0.0, "缺节点 T2 语义包")

_STOCK_ANCHOR_ANCHOR = ("anchor", "🟢代表锚点")
_STOCK_ANCHOR_WATCH = ("watch", "🟡观察占位")
_STOCK_ANCHOR_REJECT = ("reject", "🔴伪龙头")
_STOCK_ANCHOR_BLOCK = ("inherit_block", "🔴环节未过闸")
_STOCK_ANCHOR_WAIT = ("inherit_wait", "⚠️待环节T2")
_STOCK_ANCHOR_PENDING = ("data_pending", "⚠️待CVM+T2")

_N1_SCORE_MAP = {"pass": 1.0, "marginal": 0.55, "fail": 0.25}


def _duan_cfg() -> dict[str, Any]:
    return load_duan_node_gates()


def _normalize_layer(layer: str) -> str:
    lyr = (layer or "").strip().upper()
    if lyr and not lyr.startswith("L"):
        return ""
    return lyr


def infer_role_tag_from_position(position: str) -> tuple[Optional[str], str]:
    """ecosystem_position → (role_tag, source)。无法映射时 role_tag=None, source=pending。"""
    pos = (position or "").strip()
    if not pos:
        return None, "empty"
    if any(k in pos for k in ("卡脖子", "替代难", "不可替代", "新贵")):
        return "卡脖子新贵", "mapped"
    if any(k in pos for k in ("光模块",)):
        return "光模块龙头", "mapped"
    if any(k in pos for k in ("算力", "芯片", "训练")):
        return "算力精算师", "mapped"
    if any(k in pos for k in ("办公", "AI 办公", "Copilot")):
        return "办公 AI 领航者", "mapped"
    if any(k in pos for k in ("合规", "私有化")):
        return "合规与私有化先锋", "mapped"
    if any(k in pos for k in ("Agent", "智能体")):
        return "工业 Agent 中枢", "mapped"
    if any(k in pos for k in ("龙头", "巨头", "垄断", "领先")):
        for key in _ROLE_MAP:
            if key in pos:
                return key, "mapped"
        return "光模块龙头", "mapped_heuristic"
    if any(k in pos for k in ("代工", "制造", "集成", "土建", "配套", "机柜")):
        return "算力网络可视化", "mapped"
    return None, "pending"


def _eval_n1_main_chain(tier: str, layer: str) -> tuple[float, str]:
    """N1 主链地位 T1 · 返回 (score, pass|marginal|fail)。"""
    cfg = _duan_cfg()
    matrix = cfg.get("n1_matrix") or {}
    tier = tier or "配套"
    lyr = _normalize_layer(layer)
    tier_row = matrix.get(tier) or matrix.get("配套") or {}
    status = str(tier_row.get(lyr if lyr else "", tier_row.get("", "fail"))).lower()
    if status not in _N1_SCORE_MAP:
        status = "fail"
    return _N1_SCORE_MAP[status], status


def _eval_n2_bypass(node_t2: Optional[dict[str, Any]], tier: str) -> tuple[float, str]:
    cfg = _duan_cfg()
    scores = cfg.get("n2_scores") or {}
    if node_t2:
        risk = str(node_t2.get("segment_bypass_risk", "mid")).lower()
        if risk not in scores:
            risk = "mid"
        return float(scores.get(risk, 0.55)), risk
    prov = float(scores.get("provisional", 0.5))
    tier_adj = {"核心": prov + 0.1, "重要": prov, "配套": prov - 0.1}.get(tier, prov)
    return tier_adj, "provisional"


def _eval_n3_profit_pool(node_t2: Optional[dict[str, Any]], tier: str) -> float:
    cfg = _duan_cfg()
    if node_t2:
        anchor = str(node_t2.get("profit_pool_anchor", "diffuse")).lower()
        n3 = cfg.get("n3_scores") or {}
        return float(n3.get(anchor, 0.5))
    fb = cfg.get("n3_tier_fallback") or _TIER_WEIGHT
    return float(fb.get(tier, fb.get("配套", 0.45)))


def _eval_n4_horizon(node_t2: Optional[dict[str, Any]], tier: str) -> tuple[float, str]:
    cfg = _duan_cfg()
    if node_t2:
        outlook = str(node_t2.get("horizon_outlook", "stable")).lower()
        n4 = cfg.get("n4_scores") or {}
        if outlook not in n4:
            outlook = "stable"
        return float(n4.get(outlook, 0.7)), outlook
    fb = cfg.get("n4_tier_fallback") or _TIER_WEIGHT
    return float(fb.get(tier, fb.get("配套", 0.4))), "provisional"


def score_node_segment_duan(
    *,
    node_id: str = "",
    node_name: str = "",
    tier: str = "配套",
    ecosystem_layer: str = "",
    node_t2: Optional[dict[str, Any]] = None,
    require_node_t2: Optional[bool] = None,
) -> dict[str, Any]:
    """Z0-A 节点段永平闸 · N1～N4 环节级（不读标的 CVM 聚合）。"""
    cfg = _duan_cfg()
    weights = cfg.get("weights") or {"n1": 0.30, "n2": 0.30, "n3": 0.20, "n4": 0.20}
    thresholds = cfg.get("thresholds") or {"pass_aggregate": 0.65, "reject_aggregate": 0.35}
    pass_agg = float(thresholds.get("pass_aggregate", 0.65))
    reject_agg = float(thresholds.get("reject_aggregate", 0.35))
    req_t2 = cfg.get("require_node_t2", True) if require_node_t2 is None else require_node_t2

    n1_score, n1_status = _eval_n1_main_chain(tier, ecosystem_layer)
    n2_score, n2_risk = _eval_n2_bypass(node_t2, tier)
    n3_score = _eval_n3_profit_pool(node_t2, tier)
    n4_score, n4_outlook = _eval_n4_horizon(node_t2, tier)

    w1, w2, w3, w4 = (
        float(weights.get("n1", 0.30)),
        float(weights.get("n2", 0.30)),
        float(weights.get("n3", 0.20)),
        float(weights.get("n4", 0.20)),
    )
    aggregate = round(n1_score * w1 + n2_score * w2 + n3_score * w3 + n4_score * w4, 3)
    breakdown = {
        "N1_主链地位": round(n1_score, 3),
        "N2_环节bypass": round(n2_score, 3),
        "N3_利润池": round(n3_score, 3),
        "N4_时间跨度": round(n4_score, 3),
    }
    provisional = req_t2 and not node_t2

    if provisional:
        verdict, display, _, tip = _NODE_VERDICT_PROVISIONAL
    elif n1_status == "fail" or n2_risk == "high" or aggregate < reject_agg:
        verdict, display, _, tip = _NODE_VERDICT_REJECT
    elif (
        n2_risk == "mid"
        or n4_outlook == "shrink"
        or n1_status == "marginal"
        or (reject_agg <= aggregate < pass_agg)
    ):
        verdict, display, _, tip = _NODE_VERDICT_REVIEW
    elif n1_status == "pass" and n2_risk != "high" and n4_outlook in ("expand", "stable") and aggregate >= pass_agg:
        verdict, display, _, tip = _NODE_VERDICT_PASS
    else:
        verdict, display, _, tip = _NODE_VERDICT_REVIEW

    return {
        "verdict": verdict,
        "label": display.replace("✅", "").replace("❓", "").replace("❌", "").replace("⚠️", "").strip(),
        "display": display,
        "score": aggregate,
        "passed": verdict == "pass",
        "depth": "L0",
        "provisional": provisional,
        "breakdown": breakdown,
        "n1_status": n1_status,
        "n1_pass": n1_status == "pass",
        "n2_risk": n2_risk,
        "n4_outlook": n4_outlook,
        "node_id": node_id,
        "node_name": node_name,
        "node_t2_ref": node_t2.get("source") if node_t2 else None,
        "tooltip": (
            f"N1={n1_score:.2f}({n1_status}) N2={n2_score:.2f} N3={n3_score:.2f} N4={n4_score:.2f} | "
            + ("待节点 T2 语义研判 · " if provisional else "")
            + tip
        ),
    }


def _eval_s1_anchor(cvm_scores: dict[str, Any], role_tag: Optional[str]) -> tuple[bool, str, dict[str, Any]]:
    """S1 真锚点 · C7 + role_tag。"""
    c7 = cvm_scores.get("c7") or {}
    c7_pass = bool(c7.get("pass", False))
    c7_cat = str(c7.get("category", ""))
    triggers = list(c7.get("triggers") or [])
    if not role_tag:
        return False, "missing_role_tag", {"c7_category": c7_cat}
    if not c7_pass or c7_cat == "sentinel" or "representative_only" in triggers:
        return False, "sentinel_or_fail", {"c7_category": c7_cat, "triggers": triggers}
    if c7_cat in ("monopoly", "leader"):
        return True, "pass", {"c7_category": c7_cat}
    if c7_cat == "max_value":
        return True, "marginal", {"c7_category": c7_cat}
    return False, "sentinel_or_fail", {"c7_category": c7_cat}


def _eval_s2_irreplaceability(
    cvm_scores: dict[str, Any],
    *,
    node_pass: bool,
) -> tuple[bool, str]:
    """S2 不可替代初判 · 节点 ✅ 时阈值放宽一档。"""
    gates = z0_cvm_gates()
    irr = cvm_scores.get("irreplaceability") or {}
    irr_score = float(irr.get("score", 0) or 0)
    min_irr = float(
        gates.get("s2_min_irreplaceability_node_pass_relaxed", 0.30)
        if node_pass and gates.get("relax_s2_when_node_pass", True)
        else gates.get("s2_min_irreplaceability", 0.50)
    )
    if irr_score >= min_irr:
        return True, "pass"
    c2_band = (cvm_scores.get("c2") or {}).get("band", "low")
    min_band = (
        gates.get("s2_min_band_node_pass_relaxed", "marginal")
        if node_pass and gates.get("relax_s2_when_node_pass", True)
        else gates.get("s2_min_band", "acceptable")
    )
    min_ord = _BAND_ORDER.get(str(min_band), _POOL_MIN_ORD)
    if _BAND_ORDER.get(c2_band, 0) >= min_ord:
        return True, "marginal"
    return False, "fail"


def _eval_s3_pool(cvm_scores: dict[str, Any], pool_gate: Optional[dict[str, Any]], *, node_pass: bool) -> tuple[bool, list[str]]:
    """S3 进池硬闸 · C5 bypass + pool_gate。"""
    gates = z0_cvm_gates()
    min_band = (
        gates.get("s2_min_band_node_pass_relaxed", "marginal")
        if node_pass and gates.get("relax_s2_when_node_pass", True)
        else gates.get("s2_min_band", "acceptable")
    )
    if isinstance(pool_gate, dict) and "passed" in pool_gate:
        passed = bool(pool_gate.get("passed"))
        reasons = list(pool_gate.get("fail_reasons") or [])
    else:
        passed, reasons = _check_pool_gate(cvm_scores, min_band=str(min_band))
    c5 = (cvm_scores.get("c5") or {}).get("bypass_risk", "low")
    if c5 == _c5_bypass_block():
        passed = False
        reasons = reasons + ["c5_bypass_high"]
    return passed, reasons


def score_stock_duan_anchor(
    *,
    symbol: str,
    node_duan: dict[str, Any],
    ecosystem_position: str = "",
    cvm_scores: Optional[dict[str, Any]] = None,
    role_tag: Optional[str] = None,
    pool_gate: Optional[dict[str, Any]] = None,
    skip_top2_cap: bool = False,
) -> dict[str, Any]:
    """Z0-B 标的段永平闸 · S1～S3 锚点级（继承节点 verdict）。"""
    node_verdict = str(node_duan.get("verdict", ""))
    node_pass = node_verdict == "pass"
    node_review = node_verdict == "review"

    if node_verdict == "reject":
        v, d = _STOCK_ANCHOR_BLOCK
        return _stock_anchor_result(v, d, node_duan, symbol, provisional=False, reason="node_reject")
    if node_verdict == "provisional" or node_duan.get("provisional"):
        v, d = _STOCK_ANCHOR_WAIT
        return _stock_anchor_result(v, d, node_duan, symbol, provisional=True, reason="node_provisional")

    tag_source = "explicit"
    if not role_tag:
        role_tag, tag_source = infer_role_tag_from_position(ecosystem_position)

    scored_row: dict[str, Any] = {}
    if cvm_scores is None and role_tag:
        scored_row = score_symbol(symbol, role_tag=role_tag)
        cvm_scores = scored_row.get("scores") or {}
        pool_gate = scored_row.get("pool_gate")
    elif cvm_scores is None:
        cvm_scores = {}
        pool_gate = pool_gate or {}

    if not cvm_scores or tag_source in ("pending", "empty") or not role_tag:
        v, d = _STOCK_ANCHOR_PENDING
        return _stock_anchor_result(
            v, d, node_duan, symbol, provisional=True,
            reason="missing_cvm_or_role_tag", role_tag=role_tag, role_tag_source=tag_source,
            breakdown={"S1": 0, "S2": 0, "S3": 0},
        )

    s1_ok, s1_level, s1_meta = _eval_s1_anchor(cvm_scores, role_tag)
    s2_ok, s2_level = _eval_s2_irreplaceability(cvm_scores, node_pass=node_pass)
    s3_ok, s3_reasons = _eval_s3_pool(cvm_scores, pool_gate, node_pass=node_pass)
    irr = (cvm_scores.get("irreplaceability") or {}).get("score")
    c7_cat = s1_meta.get("c7_category", "")
    breakdown = {
        "S1_真锚点": 1.0 if s1_ok and s1_level == "pass" else (0.6 if s1_ok else 0.0),
        "S2_不可替代": 1.0 if s2_ok and s2_level == "pass" else (0.55 if s2_ok else 0.0),
        "S3_进池闸": 1.0 if s3_ok else 0.0,
    }

    if not s1_ok or c7_cat == "sentinel":
        v, d = _STOCK_ANCHOR_REJECT
        return _stock_anchor_result(
            v, d, node_duan, symbol, provisional=False,
            reason="s1_fail", c7_category=c7_cat, pool_gate_passed=s3_ok, role_tag=role_tag,
            role_tag_source=tag_source, irreplaceability=irr, breakdown=breakdown,
            s1_level=s1_level, s2_level=s2_level, s3_fail_reasons=s3_reasons,
        )
    if not s3_ok:
        v, d = _STOCK_ANCHOR_REJECT
        return _stock_anchor_result(
            v, d, node_duan, symbol, provisional=False,
            reason="s3_fail", c7_category=c7_cat, pool_gate_passed=False, role_tag=role_tag,
            role_tag_source=tag_source, irreplaceability=irr, breakdown=breakdown,
            s3_fail_reasons=s3_reasons,
        )
    if s1_level == "marginal" or s2_level == "marginal" or node_review:
        v, d = _STOCK_ANCHOR_WATCH
        return _stock_anchor_result(
            v, d, node_duan, symbol, provisional=bool(scored_row.get("provisional", True)),
            reason="marginal_or_node_review" if node_review else "marginal_s1_s2",
            c7_category=c7_cat, pool_gate_passed=s3_ok, role_tag=role_tag,
            role_tag_source=tag_source, irreplaceability=irr, breakdown=breakdown,
        )
    if s1_ok and s2_ok and s3_ok:
        v, d = _STOCK_ANCHOR_ANCHOR
        return _stock_anchor_result(
            v, d, node_duan, symbol, provisional=bool(scored_row.get("provisional", True)),
            c7_category=c7_cat, pool_gate_passed=True, role_tag=role_tag,
            role_tag_source=tag_source, irreplaceability=irr, breakdown=breakdown,
            pool_eligible=bool(scored_row.get("pool_eligible", True)),
        )
    v, d = _STOCK_ANCHOR_WATCH
    return _stock_anchor_result(
        v, d, node_duan, symbol, provisional=bool(scored_row.get("provisional", True)),
        c7_category=c7_cat, pool_gate_passed=s3_ok, role_tag=role_tag,
        role_tag_source=tag_source, irreplaceability=irr, breakdown=breakdown,
    )


def apply_top2_anchor_cap(
    stock_duan_by_key: dict[str, dict[str, Any]],
    *,
    max_green: Optional[int] = None,
) -> dict[str, dict[str, Any]]:
    """每节点仅保留 top N 🟢代表锚点，其余降为 🟡观察占位。"""
    gates = z0_cvm_gates()
    cap = max_green if max_green is not None else int(gates.get("max_green_anchors_per_node", 2))
    by_node: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for key, pack in stock_duan_by_key.items():
        if ":" in key:
            nid, _sym = key.split(":", 1)
        else:
            nid = str(pack.get("node_duan_ref", ""))
        by_node.setdefault(nid, []).append((key, pack))

    out = dict(stock_duan_by_key)
    for _nid, items in by_node.items():
        anchors = [(k, p) for k, p in items if p.get("verdict") == "anchor"]
        if len(anchors) <= cap:
            continue
        anchors.sort(
            key=lambda x: (
                float(x[1].get("irreplaceability") or 0),
                1 if x[1].get("pool_gate_passed") else 0,
            ),
            reverse=True,
        )
        for key, pack in anchors[cap:]:
            demoted = dict(pack)
            demoted["verdict"] = "watch"
            demoted["display"] = _STOCK_ANCHOR_WATCH[1]
            demoted["reason"] = "top2_cap_exceeded"
            demoted["watch_only"] = True
            out[key] = demoted
    return out


def _stock_anchor_result(
    verdict: str,
    display: str,
    node_duan: dict[str, Any],
    symbol: str,
    *,
    provisional: bool,
    reason: str = "",
    **extra: Any,
) -> dict[str, Any]:
    pack = {
        "verdict": verdict,
        "display": display,
        "depth": "L1",
        "provisional": provisional,
        "symbol": symbol,
        "node_duan_ref": node_duan.get("node_id") or node_duan.get("node_name"),
        "reason": reason,
        **extra,
    }
    return pack


def score_node_duan(
    *,
    node_name: str = "",
    tier: str = "配套",
    stocks: list[dict[str, Any]] | None = None,
    ecosystem_layer: str = "",
    node_id: str = "",
    node_t2: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """兼容别名 · v4.1 标的聚合已废止。"""
    _ = stocks
    return score_node_segment_duan(
        node_id=node_id,
        node_name=node_name,
        tier=tier,
        ecosystem_layer=ecosystem_layer,
        node_t2=node_t2,
        require_node_t2=True,
    )
