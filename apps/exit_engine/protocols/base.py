"""卖出协议抽象基类.

[Ref: 03_/04_维度四/.../step_01]
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from apps.exit_engine.models.position import Position
from apps.exit_engine.models.sell_signal import SellSignal, SellSignalEvent, SignalSeverity, SignalType


@dataclass
class CheckResult:
    triggered: bool
    context: dict


class BaseProtocol(ABC):
    protocol_name: SignalType
    priority: int
    buffer_days: int

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}

    @abstractmethod
    def check(self, position: Position, context: dict) -> CheckResult:
        raise NotImplementedError

    @abstractmethod
    def trigger(self, position: Position, check_result: CheckResult) -> SellSignal:
        raise NotImplementedError

    @abstractmethod
    def output_event(self, signal: SellSignal) -> SellSignalEvent:
        raise NotImplementedError

    def evaluate(self, position: Position, context: Optional[dict] = None) -> Optional[SellSignal]:
        ctx = context or {}
        result = self.check(position, ctx)
        if not result.triggered:
            return None
        return self.trigger(position, result)

    @staticmethod
    def _map_severity(priority: int) -> SignalSeverity:
        if priority <= 1:
            return SignalSeverity.EMERGENCY
        if priority == 2:
            return SignalSeverity.HIGH
        return SignalSeverity.NORMAL
