"""HealthChangeEvent schema — D0/D4 统一 payload。

[Ref: 03_/03_维度三/.../step_07_health_change事件流与10持仓测试.md §7.1 A]
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class HealthChangeEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    node_id: str = ""
    symbol: str
    name: str = ""
    old_state: str = "growing"
    new_state: str = "growing"
    old_health: float = 100.0
    new_health: float = 100.0
    old_push_level: int = 0
    new_push_level: int = 0
    rule_id: str = ""
    reason: str = ""
    thesis_status: str = "valid"
    narrative_label: str = "neutral"
    narrative_invalid_count: int = 0
    sli_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("old_health", "new_health", mode="before")
    @classmethod
    def _coerce_health(cls, v: Any) -> float:
        return float(v or 0.0)

    @property
    def health_delta(self) -> float:
        return round(self.new_health - self.old_health, 4)

    def to_stream_payload(self) -> dict[str, Any]:
        """写入 Redis Stream 的 JSON 对象（D0 + D4 字段对齐）。"""
        return {
            "event_id": self.event_id,
            "node_id": self.node_id,
            "symbol": self.symbol,
            "name": self.name,
            "old_state": self.old_state,
            "new_state": self.new_state,
            "old_health": self.old_health,
            "new_health": self.new_health,
            "health_score": self.new_health,
            "prev_score": self.old_health,
            "health_delta": self.health_delta,
            "old_push_level": self.old_push_level,
            "new_push_level": self.new_push_level,
            "push_level": self.new_push_level,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "change_reason": self.reason,
            "thesis_status": self.thesis_status,
            "narrative_label": self.narrative_label,
            "narrative_invalid_count": self.narrative_invalid_count,
            "sli_snapshot": self.sli_snapshot,
            "node_state": {"state": self.new_state},
            "timestamp": self.ts.isoformat(),
            "emitted_at": self.ts.isoformat(),
            "event_type": "health_change",
        }

    def to_redis_fields(self) -> dict[str, str]:
        import json

        return {"json": json.dumps(self.to_stream_payload(), ensure_ascii=False, default=str)}
