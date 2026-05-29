"""利润截留扫描仪 - 5 加权信号模块入口。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_04_利润截留扫描仪剧本.md]
"""
from __future__ import annotations

from typing import Protocol

from apps.deep_strike.playbooks.base_playbook import SignalResult


class Signal(Protocol):
    id: str
    weight: float

    def evaluate(self, metrics: dict) -> SignalResult:
        ...
