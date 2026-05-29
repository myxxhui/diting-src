"""信号 2：成本增速低于收入增速剪刀差（权重 0.25）。[Ref: step_04]"""
from __future__ import annotations

from apps.deep_strike.playbooks.base_playbook import SignalResult


class CostGrowthBelowRevenueSignal:
    id = "cost_growth_below_revenue"
    weight = 0.25
    gap_threshold = 0.05

    def evaluate(self, metrics: dict) -> SignalResult:
        rev = metrics.get("revenue_growth_yoy")
        cost = metrics.get("cost_growth_yoy")
        if rev is None or cost is None:
            return SignalResult(
                id=self.id,
                weight=self.weight,
                hit=False,
                value=None,
                reason="缺少 revenue_growth_yoy 或 cost_growth_yoy",
            )
        gap = rev - cost
        hit = gap > self.gap_threshold
        return SignalResult(
            id=self.id,
            weight=self.weight,
            hit=hit,
            value=gap,
            reason=f"营收-成本剪刀差 {gap:.2%} {'>' if hit else '≤'} 阈值 {self.gap_threshold:.2%}",
            raw={"revenue_growth": rev, "cost_growth": cost},
        )
