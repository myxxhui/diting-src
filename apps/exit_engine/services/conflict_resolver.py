"""多协议冲突优先级裁决（SP1 > SP3 > SP5 > SP4；同档 stable sort）。

[Ref: 03_/04_维度四/.../step_05_SP3 §1 SP1/SP3/SP5 冲突永久优先级]
[Ref: 03_/04_维度四/.../step_07_冲突处理与回测.md §3.5.1 C1~C7]
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from apps.exit_engine.models.sell_signal import SellSignalEvent, SignalType

# 数字越小优先级越高（与 L3 一致：SP1=SP3=1 同档时 SP1 主显示）
PROTOCOL_UI_PRIORITY: dict[str, int] = {
    "SP1": 0,
    "stop_loss": 0,
    "SP3": 1,
    "thesis_invalid": 1,
    "SP5": 2,
    "financial_window": 2,
    "SP2": 3,
    "take_profit": 3,
    "SP4": 4,
    "rebalance": 4,
}

# L3 协议数值 priority（升序选最高 = 数字最小）
SIGNAL_NUMERIC_PRIORITY: dict[SignalType, int] = {
    SignalType.STOP_LOSS: 1,
    SignalType.THESIS_INVALID: 1,
    SignalType.TAKE_PROFIT: 2,
    SignalType.FINANCIAL_WINDOW: 3,
    SignalType.REBALANCE: 3,
}

# 同 numeric priority 时的 tie-break（越小越优先）
SIGNAL_TIE_RANK: dict[SignalType, int] = {
    SignalType.STOP_LOSS: 0,
    SignalType.THESIS_INVALID: 1,
    SignalType.TAKE_PROFIT: 0,
    SignalType.FINANCIAL_WINDOW: 1,
    SignalType.REBALANCE: 2,
}


@dataclass
class AdviceRecord:
    protocol: str
    symbol: str
    advice: str
    priority_rank: int
    raw: dict[str, Any]


@dataclass
class ConflictResolution:
    winner: Optional[SellSignalEvent]
    all_triggered: list[SellSignalEvent] = field(default_factory=list)
    triggered_protocols: list[str] = field(default_factory=list)
    audit_id: str = field(default_factory=lambda: str(uuid.uuid4()))


def protocol_rank(protocol: str) -> int:
    return PROTOCOL_UI_PRIORITY.get(protocol, 99)


def sort_advices(records: list[AdviceRecord]) -> list[AdviceRecord]:
    """UI 排序：主显示优先级最高的一条在前，其余折叠。"""
    return sorted(records, key=lambda r: (r.priority_rank, r.protocol))


def partition_primary_secondary(records: list[AdviceRecord]) -> tuple[AdviceRecord | None, list[AdviceRecord]]:
    ordered = sort_advices(records)
    if not ordered:
        return None, []
    return ordered[0], ordered[1:]


def records_from_events(events: list[dict[str, Any]]) -> list[AdviceRecord]:
    out: list[AdviceRecord] = []
    for ev in events:
        proto = ev.get("protocol", ev.get("signal_type", "unknown"))
        out.append(
            AdviceRecord(
                protocol=str(proto),
                symbol=str(ev.get("symbol", "")),
                advice=str(ev.get("advice", "")),
                priority_rank=protocol_rank(str(proto)),
                raw=ev,
            )
        )
    return out


def _event_sort_key(event: SellSignalEvent) -> tuple[int, int, str]:
    numeric = SIGNAL_NUMERIC_PRIORITY.get(event.signal_type, 99)
    tie = SIGNAL_TIE_RANK.get(event.signal_type, 99)
    proto = event.protocol or event.signal_type.value
    return (numeric, tie, proto)


class ConflictResolver:
    """评估结果冲突仲裁：priority 升序 + 同优 stable sort。"""

    def resolve(self, events: list[SellSignalEvent]) -> ConflictResolution:
        if not events:
            return ConflictResolution(winner=None, all_triggered=[], triggered_protocols=[])

        ordered = sorted(events, key=_event_sort_key)
        winner = ordered[0]
        protocols = [e.protocol or e.signal_type.value for e in ordered]
        return ConflictResolution(
            winner=winner,
            all_triggered=ordered,
            triggered_protocols=protocols,
        )
