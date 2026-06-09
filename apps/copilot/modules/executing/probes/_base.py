"""探针模块契约 · ProbeSpec + T1 Live 上下文。

[Ref: 28_ §3 · §4.4]
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Optional, Tuple

Cadence = Literal[
    "L0",
    "L1",
    "L2",
    "L3",
    "L4",
    "dynamic",
    "intraday_15m",
    "daily",
]
Matrix = Literal["L3_Business", "L4_Game"]
T1Engine = Literal["python", "deepseek", "opus_fragment"]

OperatorResult = Optional[Tuple[str, dict[str, Any]]]


@dataclass(frozen=True)
class ProbeSpec:
    key: str
    seq: int
    matrix: Matrix
    cadence: Cadence
    job_id: str
    t1_engine: T1Engine = "python"
    per_symbol: bool = True
    implemented: bool = True
    """事件驱动型：无实质信号时 T1 静默，不计入 degraded。"""
    optional_silent: bool = False
    context_group: str | None = None


@dataclass
class T1LiveContext:
    session: Any
    symbol: str
    raw_by_key: dict[str, dict[str, Any]]
    entry_date: date | None
    redis_client: Any = None


class ExecutingProbe(ABC):
    spec: ProbeSpec

    @abstractmethod
    async def collect_t1_live(self, ctx: T1LiveContext) -> OperatorResult:
        """实盘 T1 装配；返回 (probe_key, node) 或 None（静默可选探针）。"""
