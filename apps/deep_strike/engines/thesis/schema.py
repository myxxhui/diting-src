"""ThesisCard Pydantic schema — 5 必填 + timer_signal。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_05_thesis卡片生成器.md §3.5.4]
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ValuationAnchor(BaseModel):
    method: Literal["PE", "PEG", "DCF", "PB", "PS", "watch_only"] = "PE"
    target_price: Optional[float] = None
    basis: str = ""


class EvidenceItem(BaseModel):
    evidence_type: str
    content: str = Field(min_length=5)
    url: Optional[str] = None


class ThesisCardSchema(BaseModel):
    """thesis 卡片输出 schema（write_only=proposed）。"""

    thesis_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    name: str = ""
    playbook_id: str
    confidence: float = Field(ge=0.0, le=1.0)

    # 5 必填
    thesis_summary: str = Field(min_length=50, description="≥50 字；含 symbol+剧本+逻辑")
    evidence_chain: list[EvidenceItem] = Field(min_length=3, description="≥3 条")
    risks: list[str] = Field(min_length=1, description="≥1 条；每条≥20字")
    valuation_anchor: ValuationAnchor
    action: Literal["buy", "add", "watch"]

    # Lighthouse-Alpha The Timer
    timer_signal: Optional[dict[str, Any]] = None

    scan_log_id: Optional[int] = None
    pass_event_id: Optional[str] = None
    status: str = "proposed"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("risks")
    @classmethod
    def risks_min_len(cls, v: list[str]) -> list[str]:
        for r in v:
            if len(r) < 20:
                raise ValueError(f"每条 risk 须≥20字，违规：{r!r}")
        return v
