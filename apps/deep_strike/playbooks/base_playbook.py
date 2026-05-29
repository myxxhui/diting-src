"""剧本基类与统一返回 schema。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_04_利润截留扫描仪剧本.md]
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Decision = Literal["propose", "watch", "discard"]


class SignalResult(BaseModel):
    id: str
    weight: float
    hit: bool
    value: Optional[float] = None
    reason: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PlaybookResult(BaseModel):
    playbook_id: str
    symbol: str
    decision: Decision
    confidence: float = Field(ge=0.0, le=1.0)
    signals: list[SignalResult]
    raw_metrics: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict] = Field(default_factory=list)
    pass_event_id: Optional[str] = None
    error: Optional[str] = None


class BasePlaybook(ABC):
    id: str
    cn_name: str
    priority: str = "P0"

    @abstractmethod
    async def scan(self, symbol: str, *, pass_event_id: Optional[str] = None) -> PlaybookResult:
        raise NotImplementedError

    async def batch_scan(
        self, symbols: list[str], *, pass_event_id: Optional[str] = None
    ) -> list[PlaybookResult]:
        out: list[PlaybookResult] = []
        for s in symbols:
            out.append(await self.scan(s, pass_event_id=pass_event_id))
        return out
