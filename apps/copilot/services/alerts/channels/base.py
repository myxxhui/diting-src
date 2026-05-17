"""推送通道基类。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_05]
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

from apps.copilot.services.alerts.models import Alert


@dataclass
class ChannelResult:
    channel: str
    ok: bool
    reason: str = ""
    sent_at: datetime | None = None


class BaseChannel(ABC):
    name: str = "base"

    @abstractmethod
    async def send(self, alert: Alert) -> ChannelResult:
        ...

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)
