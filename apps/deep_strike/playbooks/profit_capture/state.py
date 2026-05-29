"""LangGraph state schema。[Ref: step_04]"""
from __future__ import annotations

from typing import Any, Optional, TypedDict

from apps.deep_strike.playbooks.base_playbook import Decision, SignalResult


class ProfitCaptureState(TypedDict, total=False):
    symbol: str
    pass_event_id: Optional[str]
    raw_metrics: dict[str, Any]
    signals: list[SignalResult]
    confidence: float
    decision: Decision
    evidence: list[dict]
    error: Optional[str]
