# apps/industry_graph/backend/engine/impact_calculator.py
"""传导影响计算引擎 — 纯函数，无需 Neo4j 或 LLM"""

from ..models.enums import ImpactLevel


def calc_margin_impact(
    cost_ratio: float,
    price_change_pct: float,
    pass_through_ratio: float = 1.0,
    gross_margin: float = 0.3,
) -> dict:
    """计算毛利率受损

    Args:
        cost_ratio: 该材料占下游总成本的比例 (0~1)
        price_change_pct: 材料价格变化百分比 (e.g. 0.5 = +50%)
        pass_through_ratio: 成本传导比例 (0~1, 考虑库存缓冲后)
        gross_margin: 下游毛利率

    Returns:
        {margin_hit_pp: 毛利率受损(百分点), level: ImpactLevel}
    """
    effective_cost_increase = price_change_pct * cost_ratio * pass_through_ratio
    margin_hit_pp = effective_cost_increase * 100  # 转为百分点

    if price_change_pct < 0:
        level = ImpactLevel.BENEFIT
    elif margin_hit_pp < 3:
        level = ImpactLevel.MINOR
    elif margin_hit_pp < 8:
        level = ImpactLevel.MAJOR
    else:
        level = ImpactLevel.CRITICAL

    return {"margin_hit_pp": round(margin_hit_pp, 2), "level": level}


def estimate_lag_days(
    inventory_days: int = 30,
    contract_length_months: int = 3,
    substitute_difficulty: int = 5,
) -> int:
    """估算传导延迟天数

    Args:
        inventory_days: 下游库存天数
        contract_length_months: 下游长协周期
        substitute_difficulty: 替代难度 1-10
    """
    contract_days = contract_length_months * 30
    substitution_buffer = (10 - substitute_difficulty) * 5
    return max(0, max(inventory_days, contract_days) - substitution_buffer)
