"""M3 告警领域对象 + ORM。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_05]
[DNA: _System_DNA/00_co_pilot/dna_stage_1_启动期.yaml#deliverables.modules[2]]
"""
from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.copilot.db.database import Base


class AlertLevel(str, enum.Enum):
    RED = "red"
    ORANGE = "orange"


class AlertType(str, enum.Enum):
    REJECT = "reject"
    STOP_LOSS = "sell_signal:stop_loss"
    TAKE_PROFIT = "sell_signal:take_profit"
    HEALTH_DROP = "health_drop"
    DEGRADE = "degrade"
    THESIS_INVALID = "thesis_invalid"
    MARKET_PHASE_SHIFT = "market_phase_change"
    MARKET_PHASE_EXHAUSTION = "market_phase_exhaustion"
    REBALANCE = "sell_signal:rebalance"
    FINANCIAL_WINDOW = "sell_signal:financial_window"


ALERT_LEVEL_MAP: dict[AlertType, AlertLevel] = {
    AlertType.REJECT: AlertLevel.RED,
    AlertType.STOP_LOSS: AlertLevel.RED,
    AlertType.TAKE_PROFIT: AlertLevel.RED,
    AlertType.REBALANCE: AlertLevel.RED,
    AlertType.FINANCIAL_WINDOW: AlertLevel.ORANGE,
    AlertType.HEALTH_DROP: AlertLevel.RED,
    AlertType.DEGRADE: AlertLevel.ORANGE,
    AlertType.THESIS_INVALID: AlertLevel.ORANGE,
    AlertType.MARKET_PHASE_SHIFT: AlertLevel.ORANGE,
    AlertType.MARKET_PHASE_EXHAUSTION: AlertLevel.RED,
}


@dataclass
class Alert:
    """运行时告警载荷。"""

    alert_id: str
    user_id: str
    level: AlertLevel
    alert_type: AlertType
    symbol: str
    name: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def new(
        cls,
        *,
        user_id: str,
        alert_type: AlertType,
        symbol: str,
        name: str,
        message: str,
        payload: Optional[dict] = None,
    ) -> "Alert":
        return cls(
            alert_id=str(uuid.uuid4()),
            user_id=user_id,
            level=ALERT_LEVEL_MAP[alert_type],
            alert_type=alert_type,
            symbol=symbol,
            name=name,
            message=message,
            payload=payload or {},
        )

    @property
    def dedup_key(self) -> str:
        return f"{self.user_id}:{self.symbol}:{self.alert_type.value}"


class AlertLog(Base):
    """告警日志表（落库审计）。"""

    __tablename__ = "alert_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(String(2048), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    dedup_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    channels_sent: Mapped[dict] = mapped_column(JSON, default=dict)
    sla_met: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
