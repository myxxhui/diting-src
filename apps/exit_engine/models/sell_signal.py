"""卖出信号事件 schema.

[Ref: 03_/04_维度四/.../step_01]
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class SignalType(str, Enum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    THESIS_INVALID = "thesis_invalid"
    REBALANCE = "rebalance"
    FINANCIAL_WINDOW = "financial_window"


class SignalSeverity(str, Enum):
    EMERGENCY = "emergency"
    HIGH = "high"
    NORMAL = "normal"


@dataclass
class SellSignal:
    protocol_name: SignalType
    priority: int
    symbol: str
    position_id: str
    trigger_price: float
    current_price: float
    sell_ratio: float
    reason: str
    advice: str
    triggered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    buffer_days: int = 0
    is_revocable: bool = True
    extra: dict = field(default_factory=dict)


@dataclass
class SellSignalEvent:
    symbol: str
    signal_type: SignalType
    trigger_price: float
    current_price: float
    protocol: str
    advice: str
    severity: SignalSeverity = SignalSeverity.NORMAL
    sell_ratio: float = 1.0
    reason: str = ""
    position_id: str = ""
    audit_id: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    triggered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    buffer_end_at: Optional[datetime] = None
    is_revocable: bool = True
    source: str = "exit-engine"

    def to_stream_dict(self) -> dict[str, str]:
        payload = asdict(self)
        payload["signal_type"] = self.signal_type.value
        payload["severity"] = self.severity.value
        payload["triggered_at"] = self.triggered_at.isoformat()
        if self.buffer_end_at:
            payload["buffer_end_at"] = self.buffer_end_at.isoformat()
        else:
            payload.pop("buffer_end_at", None)
        out: dict[str, str] = {}
        for key, value in payload.items():
            if isinstance(value, Enum):
                out[key] = value.value
            elif isinstance(value, (int, float, bool)):
                out[key] = str(value)
            elif value is None:
                continue
            elif isinstance(value, (dict, list)):
                out[key] = json.dumps(value, ensure_ascii=False)
            else:
                out[key] = str(value)
        return out

    @classmethod
    def from_stream_dict(cls, raw: dict[str, str]) -> SellSignalEvent:
        return cls(
            symbol=raw["symbol"],
            signal_type=SignalType(raw["signal_type"]),
            trigger_price=float(raw["trigger_price"]),
            current_price=float(raw["current_price"]),
            protocol=raw["protocol"],
            advice=raw["advice"],
            severity=SignalSeverity(raw.get("severity", "normal")),
            sell_ratio=float(raw.get("sell_ratio", "1.0")),
            reason=raw.get("reason", ""),
            position_id=raw.get("position_id", ""),
            audit_id=raw.get("audit_id", ""),
            event_id=raw.get("event_id", str(uuid.uuid4())),
            triggered_at=datetime.fromisoformat(raw["triggered_at"]),
            buffer_end_at=datetime.fromisoformat(raw["buffer_end_at"]) if raw.get("buffer_end_at") else None,
            is_revocable=raw.get("is_revocable", "True") == "True",
            source=raw.get("source", "exit-engine"),
        )
