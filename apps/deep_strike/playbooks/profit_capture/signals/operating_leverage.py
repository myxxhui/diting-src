"""信号 3：经营杠杆释放（权重 0.25）。净利增速 / 营收增速 > 1.3。[Ref: step_04]"""
from __future__ import annotations

from apps.deep_strike.playbooks.base_playbook import SignalResult


class OperatingLeverageSignal:
    id = "operating_leverage"
    weight = 0.25
    ratio_threshold = 1.3

    def evaluate(self, metrics: dict) -> SignalResult:
        rev = metrics.get("revenue_growth_yoy")
        net = metrics.get("net_profit_growth_yoy")
        if rev is None or net is None:
            return SignalResult(
                id=self.id,
                weight=self.weight,
                hit=False,
                value=None,
                reason="缺少 revenue_growth_yoy 或 net_profit_growth_yoy",
            )
        if rev <= 0:
            return SignalResult(
                id=self.id,
                weight=self.weight,
                hit=False,
                value=None,
                reason="营收负增长，杠杆判断失效",
            )
        ratio = net / rev
        hit = ratio > self.ratio_threshold
        return SignalResult(
            id=self.id,
            weight=self.weight,
            hit=hit,
            value=ratio,
            reason=f"净利/营收增速 = {ratio:.2f} {'>' if hit else '≤'} {self.ratio_threshold}",
            raw={"net_profit_growth": net, "revenue_growth": rev},
        )
