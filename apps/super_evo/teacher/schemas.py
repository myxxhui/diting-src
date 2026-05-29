"""Teacher 蒸馏 Pydantic 模型。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_02]
[DNA: _System_DNA/05_super_evo/dna_stage_1_启动期.yaml#deliverables.components[C1]]
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


TaskType = Literal["financial_fraud", "shareholder", "related_party", "thesis", "nli"]


class DistillInput(BaseModel):
    """单条蒸馏输入。"""

    task_type: TaskType
    raw_data: dict[str, Any]
    context: dict[str, Any] | None = None
    sample_id: str | None = None

    @field_validator("raw_data")
    @classmethod
    def _non_empty(cls, v: dict) -> dict:
        if not v:
            raise ValueError("raw_data must be non-empty dict")
        return v


class DistillMetadata(BaseModel):
    task_type: TaskType
    teacher_model: str
    distill_timestamp: str
    verified: bool = False
    verifier: str | None = None
    sample_id: str | None = None
    dvc_version: str | None = None
    batch_id: str | None = None


class DistillOutput(BaseModel):
    """符合 LLaMA-Factory alpaca 格式的单条样本。

    output 字段必须为有效 JSON 字符串（含 risk_score/decision/evidence/reasoning/confidence）。
    """

    instruction: str
    input: str
    output: str
    metadata: DistillMetadata

    def to_jsonl_line(self) -> str:
        import json

        return json.dumps(self.model_dump(), ensure_ascii=False)


class DistillBatchResult(BaseModel):
    batch_id: str
    task_type: TaskType
    num_total: int
    num_success: int
    num_failed: int
    jsonl_path: str
    minio_uri: str | None = None
    started_at: datetime
    finished_at: datetime
    errors: list[str] = Field(default_factory=list)

    @property
    def throughput_per_day(self) -> float:
        elapsed = (self.finished_at - self.started_at).total_seconds()
        if elapsed <= 0:
            return 0.0
        return self.num_success / elapsed * 86400
