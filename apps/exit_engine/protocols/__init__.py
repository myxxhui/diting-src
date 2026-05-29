"""协议注册表.[Ref: step_01]"""
from __future__ import annotations

from apps.exit_engine.protocols.base import BaseProtocol, CheckResult
from apps.exit_engine.protocols.rebalance import RebalanceProtocol
from apps.exit_engine.protocols.sp5_financial_window import Sp5FinancialWindowProtocol
from apps.exit_engine.protocols.stop_loss import StopLossProtocol
from apps.exit_engine.protocols.take_profit import TakeProfitProtocol
from apps.exit_engine.protocols.thesis_invalid import ThesisInvalidProtocol

PROTOCOL_CLASSES: list[type[BaseProtocol]] = [
    StopLossProtocol,
    TakeProfitProtocol,
    ThesisInvalidProtocol,
    RebalanceProtocol,
    Sp5FinancialWindowProtocol,
]

__all__ = [
    "BaseProtocol",
    "CheckResult",
    "StopLossProtocol",
    "TakeProfitProtocol",
    "ThesisInvalidProtocol",
    "RebalanceProtocol",
    "Sp5FinancialWindowProtocol",
    "PROTOCOL_CLASSES",
]
