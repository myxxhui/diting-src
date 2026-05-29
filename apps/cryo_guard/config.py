"""cryo-guard 配置中心（pydantic-settings 读取 .env）。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_01]
[DNA: _System_DNA/01_cryo_guard/dna_stage_1_启动期.yaml#tech_stack]
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CryoGuardSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CRYO_",
        case_sensitive=False,
        extra="ignore",
    )

    service_name: str = "cryo-guard"
    port: int = 8081
    log_level: str = "INFO"

    db_url: str = "sqlite+aiosqlite:///./data/cryo_guard.db"
    redis_url: str = "redis://localhost:6379/1"

    vllm_base_url: str = "http://localhost:8000/v1"
    vllm_api_key: str = "dummy"

    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection_prefix: str = "diting_"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "diting123"

    teacher_api_key: str = ""
    teacher_base_url: str = "https://api.anthropic.com"
    teacher_model: str = "claude-3-5-sonnet-20241022"

    upstream_streams: list[str] = Field(
        default_factory=lambda: [
            "events:cryo_guard:reject",
            "events:cryo_guard:degrade",
            "events:cryo_guard:pass",
            "events:thrust:thesis_proposed",
            "events:monitor:health_change",
            "events:exit:sell_signal",
            "events:flywheel:lora_updated",
        ]
    )

    reject_thresholds: dict[str, float] = Field(
        default_factory=lambda: {
            "financial_fraud": 0.85,
            "shareholder_integrity": 0.80,
            "related_party": 0.80,
        }
    )
    degrade_thresholds: dict[str, float] = Field(
        default_factory=lambda: {
            "financial_fraud": 0.60,
            "shareholder_integrity": 0.55,
            "related_party": 0.55,
        }
    )

    lora_dir: str = "./loras"
    holdout_dir: str = "./training/data/holdout"
    verified_dir: str = "./training/data/verified"


settings = CryoGuardSettings()
