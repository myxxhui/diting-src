"""证据链 Pydantic 模型。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_03_证据链构建器.md]
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class EvidenceType(str, Enum):
    FINANCIAL = "financial"
    ANNOUNCEMENT = "announcement"
    INDUSTRY = "industry"
    SUPPLY_CHAIN = "supply_chain"
    PHYSICAL = "physical"  # Critic physical_gate 证据


class Evidence(BaseModel):
    type: EvidenceType
    source: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=2048)
    evidence_date: date | None = None
    url: str | None = None
    source_id: str | None = Field(default=None, max_length=128)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    # Critic 物理门禁专用字段（非 PHYSICAL 类型时为 None）
    physical_gate: bool | None = None
    raw_data: dict = Field(default_factory=dict)

    def to_db_row(self, symbol: str, scan_id: str, evidence_idx: int) -> dict:
        return {
            "symbol": symbol,
            "scan_id": scan_id,
            "evidence_idx": evidence_idx,
            "evidence_type": self.type.value,
            "source": self.source,
            "source_id": self.source_id or self.source,
            "content": self.content,
            "confidence": self.confidence,
            "occurred_at": (
                datetime.combine(self.evidence_date, datetime.min.time())
                if self.evidence_date
                else None
            ),
            "url": self.url,
            "raw": self.raw_data or None,
            "physical_gate": self.physical_gate,
        }


class EvidenceChain(BaseModel):
    """聚合：返回给上层 thesis 生成器。"""

    symbol: str
    items: list[Evidence] = Field(min_length=3)
    industry_compared: bool = False
    timeseries_window_quarters: int = 0
