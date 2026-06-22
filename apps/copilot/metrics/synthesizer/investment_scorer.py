"""Z0+ 投资级评分器 · 四轴加权引擎。

将 B2 聚合输出的政策信号（轴一/轴四）与预配置的行业知识画像（轴二/轴三）融合，
计算投资级综合评分 Z0+。

[Ref: 36_ §5.5 · 34_ §3.0a Z0+]

数据来源：
- 轴一·政策动量：📄 B2 文档聚合（impact_score × source_authority × impl_status × time_decay）
- 轴二·商业轨迹：📄 LLM提取收入传导类型 + 📋 YAML预配行业成长阶段和利润池
- 轴三·资本引力：📄 LLM提取叙事催化类型 + 📋 YAML预配估值弹性和机构覆盖
- 轴四·落地质量：📄 LLM提取 implementation_strength + toolkit
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PROFILE_CFG = (
    Path(__file__).resolve().parents[3]
    / "data" / "config" / "metrics" / "z0_investment_profile.yaml"
)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _load_profile() -> dict[str, Any]:
    """加载投资画像配置。"""
    if not _PROFILE_CFG.is_file():
        return {"investment_profiles": {}, "score_mapping": {}}
    with _PROFILE_CFG.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _get_profile(sector: str) -> dict[str, Any]:
    """获取单个赛道的投资画像。"""
    profiles = _load_profile().get("investment_profiles") or {}
    return profiles.get(sector) or {}


def _get_mapping() -> dict[str, dict[str, float]]:
    """获取评分映射表（分类 → 0-1 分数）。"""
    return _load_profile().get("score_mapping") or {}


def _compute_policy_momentum(b2: dict[str, Any]) -> float:
    """轴一：政策动量（30%权重）。
    
    纯从 B2 聚合结果计算：
    - composite_score 为三因子衰减后的基础分
    - policy_acceleration 判断政策是否处于爆发期
    - regime_change_count 判断是否有政策拐点
    """
    composite = b2.get("composite_score") or 0.0
    
    # 政策加速度：近30天密度/前60天密度
    accel = b2.get("policy_acceleration") or 1.0
    accel_bonus = min(1.20, max(0.85, accel))
    
    momentum = float(composite) * accel_bonus
    
    # 政策拐点加成
    rc = int(b2.get("regime_change_doc_count") or 0)
    if rc > 0:
        momentum = min(1.0, momentum * 1.10)
    
    # 政策阶段加成
    phase = str(b2.get("dominant_policy_phase") or "maturation")
    mapping = _get_mapping()
    phase_bonus = (mapping.get("policy_phase_bonus") or {}).get(phase, 1.0)
    momentum = min(1.0, momentum * phase_bonus)
    
    return _clamp01(momentum)


def _compute_commercial_trajectory(b2: dict[str, Any], profile: dict[str, Any]) -> float:
    """轴二：商业轨迹（30%权重）。
    
    混合来源：
    - revenue_transmission_type（📄 LLM 从文档提取 · 权重 40%）
    - growth_stage           （📋 YAML 预配 · 权重 35%）
    - profit_pool            （📋 YAML 预配 · 权重 25%）
    """
    mapping = _get_mapping()
    
    # 收入传导效率（从文档提取）
    rev_type = str(b2.get("dominant_revenue_model") or "political_rhetoric")
    rev_scores = mapping.get("revenue_transmission_type") or {}
    rev_score = rev_scores.get(rev_type, 0.30)
    
    # 行业成长阶段（YAML 预配）
    growth = profile.get("growth_stage", "mature")
    growth_scores = mapping.get("growth_stage") or {}
    growth_score = growth_scores.get(growth, 0.35)
    
    # 利润池集中度（YAML 预配）
    profit = profile.get("profit_pool", "fragmented")
    profit_scores = mapping.get("profit_pool") or {}
    profit_score = profit_scores.get(profit, 0.40)
    
    return rev_score * 0.40 + growth_score * 0.35 + profit_score * 0.25


def _compute_capital_gravity(b2: dict[str, Any], profile: dict[str, Any]) -> float:
    """轴三：资本引力（25%权重）。
    
    混合来源：
    - valuation_tier    （📋 YAML 预配 · 权重 40%）
    - narrative_type    （📄 LLM 从文档提取 · 权重 35%）
    - institutional_flow（📋 YAML 预配 · 权重 25%）
    """
    mapping = _get_mapping()
    
    # 估值扩张空间（YAML 预配）
    val_tier = profile.get("valuation_tier", "traditional_manufacturing")
    val_scores = mapping.get("valuation_tier") or {}
    val_score = val_scores.get(val_tier, 0.40)
    
    # 叙事驱动力（从文档提取）
    narr_type = str(b2.get("dominant_narrative_type") or "political_slogan")
    narr_scores = mapping.get("narrative_catalyst_type") or {}
    narr_score = narr_scores.get(narr_type, 0.30)
    
    # 机构资金覆盖（YAML 预配）
    inst = profile.get("institutional_flow", "limited_coverage")
    inst_scores = mapping.get("institutional_flow") or {}
    inst_score = inst_scores.get(inst, 0.30)
    
    return val_score * 0.40 + narr_score * 0.35 + inst_score * 0.25


def _compute_implementation_quality(b2: dict[str, Any]) -> float:
    """轴四：落地质量（15%权重）。
    
    全部从文档提取：
    - implementation_strength（落地力度分类）
    - toolkit 丰富度微调
    """
    mapping = _get_mapping()
    impl_scores = mapping.get("implementation_quality") or {}
    
    imp_str = str(b2.get("best_imp_strength") or "light")
    base_score = impl_scores.get(imp_str, 0.30)
    
    # 工具包丰富度微调
    toolkit = b2.get("avg_toolkit") or {}
    tk_scores = mapping.get("toolkit_richness") or {}
    tk_base = tk_scores.get("base_score", 0.30)
    tk_bonus = tk_scores.get("per_point_bonus", 0.03)
    tk_max_mult = tk_scores.get("max_multiplier", 1.20)
    
    if toolkit:
        # 计算所有toolkit维度的平均值
        avg_tk = sum(toolkit.values()) / max(len(toolkit), 1)
        if avg_tk > 0:
            bonus = (avg_tk - tk_base) * tk_bonus
            base_score = min(base_score * min(1.0 + bonus, tk_max_mult), 1.0)
    
    return _clamp01(base_score)


def score_investment_grade(sector: str, b2_aggregate: dict[str, Any]) -> dict[str, Any]:
    """对单个赛道计算四轴投资级评分。
    
    Args:
        sector: 规范赛道名（如 "AI算力"）
        b2_aggregate: B2 聚合输出的该赛道完整数据
    
    Returns:
        {
            "z0_plus_score": 0.80,
            "policy_momentum": 0.75,          # 轴一
            "commercial_trajectory": 0.90,    # 轴二
            "capital_gravity": 0.88,          # 轴三
            "implementation_quality": 0.60,   # 轴四
            "breakdown": {                    # 详细拆解
                "revenue_model": "market_creation",
                "growth_stage": "explosive",
                "profit_pool": "tech_oligopoly",
                "valuation_tier": "tech_growth",
                "narrative_type": "national_strategy_tech",
                "institutional_flow": "dedicated_etf",
                "policy_phase": "acceleration",
                "policy_acceleration": 1.85,
                "regime_change_count": 2,
                "imp_strength": "targeted",
            }
        }
    """
    profile = _get_profile(sector)
    
    # 四轴计算
    pm = _compute_policy_momentum(b2_aggregate)
    ct = _compute_commercial_trajectory(b2_aggregate, profile)
    cg = _compute_capital_gravity(b2_aggregate, profile)
    iq = _compute_implementation_quality(b2_aggregate)
    
    # 加权合成
    final = pm * 0.30 + ct * 0.30 + cg * 0.25 + iq * 0.15
    
    # 提取拆解信息
    breakdown = {
        "revenue_model": str(b2_aggregate.get("dominant_revenue_model", "political_rhetoric")),
        "growth_stage": profile.get("growth_stage", "mature"),
        "profit_pool": profile.get("profit_pool", "fragmented"),
        "valuation_tier": profile.get("valuation_tier", "traditional_manufacturing"),
        "narrative_type": str(b2_aggregate.get("dominant_narrative_type", "political_slogan")),
        "institutional_flow": profile.get("institutional_flow", "limited_coverage"),
        "policy_phase": str(b2_aggregate.get("dominant_policy_phase", "maturation")),
        "policy_acceleration": round(float(b2_aggregate.get("policy_acceleration", 1.0)), 2),
        "regime_change_count": int(b2_aggregate.get("regime_change_doc_count") or 0),
        "imp_strength": str(b2_aggregate.get("best_imp_strength", "light")),
    }
    
    return {
        "z0_plus_score": round(_clamp01(final), 4),
        "policy_momentum": round(pm, 4),
        "commercial_trajectory": round(ct, 4),
        "capital_gravity": round(cg, 4),
        "implementation_quality": round(iq, 4),
        "breakdown": breakdown,
    }


def get_profile_details_for_sector(sector: str) -> dict[str, Any]:
    """返回某赛道的YAML投资画像（供前端展示）。"""
    profile = _get_profile(sector)
    if not profile:
        return {}
    mapping = _get_mapping()
    
    # 查找各维度的中文标签
    growth_labels = {"explosive": "爆发期", "rapid_growth": "快速成长", "steady_growth": "稳定增长", "mature": "成熟期", "declining": "衰退期"}
    profit_labels = {"tech_oligopoly": "技术寡头", "oligopoly_premium": "寡头壁垒", "differentiated": "差异化竞争", "fragmented": "高度分散"}
    val_labels = {"tech_growth": "科技成长", "healthcare_biotech": "医药生物", "premium_consumer": "消费", "industrial_tech": "工业科技", "traditional_manufacturing": "传统制造", "utility_defensive": "防御估值"}
    inst_labels = {"dedicated_etf": "有ETF/主题基金", "broad_coverage": "宽基覆盖", "limited_coverage": "覆盖少"}
    
    rev_labels = {"direct_cash": "直接补贴", "market_creation": "创造市场", "government_procurement": "政府采购", "cost_reduction": "降成本", "standards_enabler": "标准赋能", "political_rhetoric": "政治表态"}
    narr_labels = {"national_strategy_tech": "国家战略科技", "new_industry_birth": "全新产业", "modernization_leap": "现代化跨越", "consumption_lifestyle": "消费升级", "regulator_fix": "监管修复", "basic_necessity_security": "基础安全", "political_slogan": "政治口号"}
    phase_labels = {"initiation": "初启期", "acceleration": "加速期", "maturation": "成熟期", "phase_out": "退出期"}
    
    return {
        "description": profile.get("description", ""),
        "growth_stage": {"key": profile.get("growth_stage"), "label": growth_labels.get(profile.get("growth_stage", ""), profile.get("growth_stage"))},
        "profit_pool": {"key": profile.get("profit_pool"), "label": profit_labels.get(profile.get("profit_pool", ""), profile.get("profit_pool"))},
        "valuation_tier": {"key": profile.get("valuation_tier"), "label": val_labels.get(profile.get("valuation_tier", ""), profile.get("valuation_tier"))},
        "institutional_flow": {"key": profile.get("institutional_flow"), "label": inst_labels.get(profile.get("institutional_flow", ""), profile.get("institutional_flow"))},
        # 以下为从文档提取的标签（默认值 + 标签）
        "revenue_labels": rev_labels,
        "narrative_labels": narr_labels,
        "phase_labels": phase_labels,
    }


__all__ = [
    "score_investment_grade",
    "get_profile_details_for_sector",
]
