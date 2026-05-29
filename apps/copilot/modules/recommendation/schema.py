"""thesis_proposed 事件 schema 校验 - 5 必填字段。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_04]
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, field_validator

ALLOWED_ACTIONS = ("buy", "add", "watch")
ALLOWED_USER_ACTIONS = ("join", "consider", "not_interested")


class ValuationAnchor(BaseModel):
    method: str = Field(min_length=1, description="估值方法 PE/PB/DCF/...")
    target_price: Optional[float] = None
    target_pe: Optional[float] = None
    target_pb: Optional[float] = None
    note: Optional[str] = None


class ThesisProposedPayload(BaseModel):
    """thesis_proposed 事件 5 必填。"""

    event_id: str
    event_type: Literal["thesis_proposed"] = "thesis_proposed"
    timestamp: datetime
    trace_id: Optional[str] = None

    thesis_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    name: str = Field(min_length=1)

    thesis_summary: Annotated[str, Field(min_length=20, max_length=2000)]
    evidence_chain: list[str] = Field(min_length=3)
    risks: list[str] = Field(min_length=1)
    valuation_anchor: ValuationAnchor
    action: str

    pass_event_id: Optional[str] = None

    @field_validator("evidence_chain", "risks")
    @classmethod
    def _strip_each(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v if isinstance(s, str) and s.strip()]
        if not cleaned:
            raise ValueError("空列表或全为空字符串")
        return cleaned

    @field_validator("action")
    @classmethod
    def _valid_action(cls, v: str) -> str:
        if v not in ALLOWED_ACTIONS:
            raise ValueError(f"action 必须 ∈ {ALLOWED_ACTIONS}")
        return v


class UserActionPayload(BaseModel):
    action: str

    @field_validator("action")
    @classmethod
    def _valid(cls, v: str) -> str:
        if v not in ALLOWED_USER_ACTIONS:
            raise ValueError(f"action 必须 ∈ {ALLOWED_USER_ACTIONS}")
        return v
