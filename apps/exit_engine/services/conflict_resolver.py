"""多协议冲突优先级裁决（SP1 > SP3 > SP5 > SP4）。

[Ref: 03_/04_维度四/.../step_05_SP3 §1 SP1/SP3/SP5 冲突永久优先级]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 数字越小优先级越高（与 L3 一致：SP1=SP3=1 同档时 SP1 主显示）
PROTOCOL_UI_PRIORITY: dict[str, int] = {
    "SP1": 0,
    "stop_loss": 0,
    "SP3": 1,
    "thesis_invalid": 1,
    "SP5": 2,
    "financial_window": 2,
    "SP4": 3,
    "rebalance": 3,
    "SP2": 2,
    "take_profit": 2,
}


@dataclass
class AdviceRecord:
    protocol: str
    symbol: str
    advice: str
    priority_rank: int
    raw: dict[str, Any]


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
