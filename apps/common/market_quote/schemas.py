"""行情标准化 schema。

[Ref: 03_/_共享规约/21_行情数据源降级与断路器规约.md §二]
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Optional


@dataclass(frozen=True)
class RealtimeQuote:
    symbol: str
    close: float
    prev_close: float
    change_pct: float
    volume: int
    timestamp: datetime
    source: str
    is_stale: bool

    def to_json(self) -> str:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> RealtimeQuote:
        d: dict[str, Any] = json.loads(raw)
        return cls(
            symbol=d["symbol"],
            close=float(d["close"]),
            prev_close=float(d["prev_close"]),
            change_pct=float(d["change_pct"]),
            volume=int(d["volume"]),
            timestamp=datetime.fromisoformat(d["timestamp"]),
            source=d["source"],
            is_stale=bool(d["is_stale"]),
        )


@dataclass(frozen=True)
class Kline:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    adjust: str

    def to_json(self) -> str:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> Kline:
        d: dict[str, Any] = json.loads(raw)
        return cls(
            date=date.fromisoformat(d["date"]),
            open=float(d["open"]),
            high=float(d["high"]),
            low=float(d["low"]),
            close=float(d["close"]),
            volume=int(d["volume"]),
            adjust=d["adjust"],
        )


@dataclass(frozen=True)
class SourceHealth:
    source: str
    status: str
    last_ok_at: Optional[datetime]
    consecutive_failures: int
    tripped_until: Optional[datetime]
