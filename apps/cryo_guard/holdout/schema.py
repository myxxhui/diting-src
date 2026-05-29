"""Holdout JSON 的 Pydantic Schema（与 L3 five_hundred_holdout 一致）。

[Ref: 03_/01_维度一_极寒防御/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

DecisionT = Literal["reject", "degrade", "pass"]
EngineT = Literal["financial_fraud", "shareholder_integrity", "related_party"]


class HoldoutCaseFile(BaseModel):
    """单条 Holdout 案例文件结构。"""

    model_config = {"extra": "ignore"}

    case_id: str = Field(..., pattern=r"^H\d{3}$")
    symbol: str = Field(..., min_length=6, max_length=6)
    company_name: str
    fraud_type: str
    target_engine: EngineT
    fraud_start_year: int = Field(..., ge=1990, le=2100)
    exposure_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    ground_truth_decision: DecisionT
    ground_truth_score: float = Field(..., ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)
    notes: Optional[str] = None

    @field_validator("evidence")
    @classmethod
    def _evidence_nonempty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("evidence 至少 1 条")
        return v

    @model_validator(mode="after")
    def _score_vs_decision(self) -> HoldoutCaseFile:
        d, s = self.ground_truth_decision, self.ground_truth_score
        if d == "reject" and s < 0.80:
            raise ValueError("reject 案例的 score 必须 ≥ 0.80")
        if d == "pass" and s > 0.40:
            raise ValueError("pass 案例的 score 必须 ≤ 0.40")
        return self
