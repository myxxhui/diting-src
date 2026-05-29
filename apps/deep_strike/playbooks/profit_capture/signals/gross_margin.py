"""信号 1：毛利率环比提升 > 2%（权重 0.30）。[Ref: step_04]"""
from __future__ import annotations

from apps.deep_strike.playbooks.base_playbook import SignalResult


class GrossMarginQoQUpSignal:
    id = "gross_margin_qoq_up"
    weight = 0.30
    threshold = 0.02

    def evaluate(self, metrics: dict) -> SignalResult:
        qoq = metrics.get("gross_margin_qoq")
        if qoq is None:
            return SignalResult(
                id=self.id,
                weight=self.weight,
                hit=False,
                value=None,
                reason="缺少 gross_margin_qoq",
            )
        hit = qoq > self.threshold
        return SignalResult(
            id=self.id,
            weight=self.weight,
            hit=hit,
            value=qoq,
            reason=f"毛利率 QoQ {qoq:.2%} {'>' if hit else '≤'} 阈值 {self.threshold:.2%}",
            raw={"gross_margin": metrics.get("gross_margin")},
        )
