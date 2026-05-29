"""events:flywheel:training_completed 事件 Schema 与发布器。

注意：此事件只表示"训练已完成"；模型是否上线由 step_07 灰度 + step_08 lora_updated 决定。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_04_C3_LLaMA_Factory训练流水线.md]
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import redis
from pydantic import BaseModel, Field

from apps.super_evo.config import settings


class TrainingCompletedEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = "training_completed"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

    lora_name: str
    lora_version: str
    base_model: str
    rank: int
    dataset_path: str
    metrics: dict
    output_path: str
    config_path: str
    dvc_version: str | None = None

    def to_message(self) -> dict[str, str]:
        return {"data": json.dumps(self.model_dump(), ensure_ascii=False)}


class TrainingEventPublisher:
    STREAM_NAME = "events:flywheel:training_completed"

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis = redis.from_url(redis_url or settings.redis_url, decode_responses=True)

    def publish(self, event: TrainingCompletedEvent) -> str:
        return self._redis.xadd(self.STREAM_NAME, event.to_message())

    def length(self) -> int:
        try:
            return int(self._redis.xlen(self.STREAM_NAME))
        except Exception:
            return 0
