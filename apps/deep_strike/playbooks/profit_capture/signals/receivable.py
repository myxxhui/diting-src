"""信号 4：应收账款周转改善（权重 0.10）。[Ref: step_04]"""
from __future__ import annotations

from apps.deep_strike.playbooks.base_playbook import SignalResult


class ReceivableTurnoverUpSignal:
    id = "receivable_turnover_up"
    weight = 0.10

    def evaluate(self, metrics: dict) -> SignalResult:
        qoq = metrics.get("receivable_turnover_qoq")
        if qoq is None:
            return SignalResult(
                id=self.id,
                weight=self.weight,
                hit=False,
                value=None,
                reason="缺少 receivable_turnover_qoq",
            )
        hit = qoq > 0
        return SignalResult(
            id=self.id,
            weight=self.weight,
            hit=hit,
            value=qoq,
            reason=f"应收周转 QoQ {qoq:.2f} {'>' if hit else '≤'} 0",
        )
