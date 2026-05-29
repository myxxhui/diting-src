"""deep-strike 配置中心。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_01]
[DNA: _System_DNA/02_deep_strike/dna_stage_1_启动期.yaml#tech_stack]
"""
from __future__ import annotations

import os

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DeepStrikeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DEEP_STRIKE_",
        extra="ignore",
    )

    service_name: str = "deep-strike"
    port: int = 8082
    log_level: str = "INFO"

    db_url: str = "sqlite+aiosqlite:///./data/deep_strike.db"
    redis_url: str = "redis://localhost:6379/0"

    upstream_streams: list[str] = Field(
        default_factory=lambda: [
            "events:cryo_guard:pass",
            "events:flywheel:lora_updated",
            "events:deep_strike:timer_signal",
        ]
    )

    downstream_stream: str = "events:thrust:thesis_proposed"
    timer_signal_stream: str = "events:deep_strike:timer_signal"
    vllm_base_url: str = "http://localhost:8000/v1"
    base_model: str = "Qwen2.5-7B-Instruct"
    thesis_lora_name: str = "thesis_lora_v1"
    risk_lora_name: str = "risk_lora_v1"
    weekly_thesis_quota: int = 5
    propose_confidence_threshold: float = 0.7
    watch_confidence_threshold: float = 0.4
    data_dir: str = "./data/deep_strike"

    @model_validator(mode="after")
    def _merge_redis_url(self) -> "DeepStrikeSettings":
        env_redis = os.environ.get("REDIS_URL", "").strip()
        if env_redis and self.redis_url.startswith("redis://localhost"):
            self.redis_url = env_redis
        return self


settings = DeepStrikeSettings()
