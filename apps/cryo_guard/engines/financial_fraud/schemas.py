"""财务测谎引擎 Schema 定义。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_04_财务测谎引擎LoRA §3.5.2 N5]
"""
from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class FraudLabel(str, Enum):
    FRAUD = "fraud"
    NORMAL = "normal"


class EvidenceItem(BaseModel):
    source_table: str = Field(..., description="来源表名，如 financial_reports")
    source_period: str = Field(..., description="报告期，如 2023-12-31")
    human_readable_reason: str = Field(..., min_length=5, description="可读原因")


class LLMInterrogatorOutput(BaseModel):
    """N5 llm_interrogator 输出 Schema。[Ref: step_04 §3.5.2·N5]"""
    label: FraudLabel
    confidence: float = Field(..., ge=0.0, le=1.0)
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    category: str = ""
    evidence: list[EvidenceItem] = Field(default_factory=list)
    reason_zh: str = ""
    lora_loaded: bool = True


class FinancialFraudReport(BaseModel):
    """财务测谎引擎完整输出报告。"""
    symbol: str
    report_period: str
    label: FraudLabel
    confidence: float
    risk_level: RiskLevel
    features: dict = Field(default_factory=dict)
    peer_fallback: Optional[str] = None
    history_insufficient: bool = False
    evidence: list[EvidenceItem] = Field(default_factory=list)
    reason_zh: str = ""
    lora_loaded: bool = True
    missing_fields: list[str] = Field(default_factory=list)
