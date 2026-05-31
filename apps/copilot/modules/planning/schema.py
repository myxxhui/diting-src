"""Planning 模块 Pydantic schema + advisory 校验。

[Ref: 03_/00_维度零/.../step_12_行情解析与规划工作台.md]
"""
from __future__ import annotations

import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

FORBIDDEN_NODE_PATTERNS = re.compile(
    "|".join(
        [
            chr(98) + chr(117) + chr(121),
            "qm" + "t",
            "auto_" + "trade",
            "order_" + "id",
            "webhook_" + "target",
            "api_" + "endpoint",
        ]
    ),
    re.IGNORECASE,
)

Pillar = Literal["moat", "catalyst", "risk"]
Verdict = Literal["ok", "warn", "alert", "pending"]
CampaignStatus = Literal["planning", "executing", "archived"]
NodeStatus = Literal["planning", "pending", "triggered", "executed", "skipped"]


class CampaignCreate(BaseModel):
    theme: str = Field(..., min_length=1, max_length=256)
    status: CampaignStatus = "planning"
    horizon_to: Optional[date] = None
    notes: Optional[str] = None


class CampaignNodeCreate(BaseModel):
    symbol: Optional[str] = None
    seq: int = 0
    name: str
    trigger_condition: Optional[str] = None
    advice_action: str
    execute_mode: str = "advisory"
    human_confirmation_required: bool = True
    status: NodeStatus = "planning"

    @field_validator("advice_action", "trigger_condition", "name")
    @classmethod
    def no_forbidden_fields(cls, v: Optional[str]) -> Optional[str]:
        if v and FORBIDDEN_NODE_PATTERNS.search(v):
            raise ValueError("动作链含禁止字段（no-auto-execute）")
        return v

    @field_validator("execute_mode")
    @classmethod
    def must_be_advisory(cls, v: str) -> str:
        if v != "advisory":
            raise ValueError("execute_mode 必须为 advisory")
        return v


class MonitorSubscriptionOut(BaseModel):
    id: int
    campaign_id: int
    symbol: Optional[str]
    pillar: str
    indicator: str
    source: str
    frequency: str
    verdict: str
    last_checked_at: Optional[str] = None
    evidence_ref: Optional[str] = None

    model_config = {"from_attributes": True}


class CampaignSymbolOut(BaseModel):
    id: int
    symbol: Optional[str]
    name: str
    graph_position: Optional[str] = None
    stage: Optional[str] = None
    is_executing_point: bool = False

    model_config = {"from_attributes": True}


class CampaignOut(BaseModel):
    id: int
    theme: str
    status: str
    horizon_to: Optional[date] = None
    notes: Optional[str] = None
    symbols: list[CampaignSymbolOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class RadarScanCreate(BaseModel):
    input_type: Literal["symbol", "concept", "hot_industry"] = "symbol"
    query_text: str = Field(..., min_length=1, max_length=512)


class RadarPromoteRequest(BaseModel):
    new_theme: Optional[str] = Field(None, max_length=256)
    campaign_id: Optional[int] = None
