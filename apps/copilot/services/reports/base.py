"""报告基类：负责聚合数据 + 渲染调度。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class ReportContext:
    user_id: str
    period_label: str
    period_start: date
    period_end: date
    is_demo: bool = False
    payload: dict[str, Any] = field(default_factory=dict)


class BaseReportGenerator(ABC):
    """报告生成器基类。"""

    kind: str = "base"

    @abstractmethod
    async def aggregate(self, user_id: str, period_date: date) -> ReportContext:
        ...
