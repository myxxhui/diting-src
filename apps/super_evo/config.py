"""super-evo 配置中心。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_01]
[DNA: _System_DNA/05_super_evo/dna_stage_1_启动期.yaml#tech_stack]
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SuperEvoSettings(BaseSettings):
    """super-evo 服务配置。

    所有字段都可通过 SUPER_EVO_* 环境变量覆盖；额外特殊环境变量：
    - WANDB_API_KEY: 直接由 wandb 库读取，本类只校验存在性
    - ANTHROPIC_API_KEY: 给 Teacher 蒸馏使用，本类只校验存在性
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SUPER_EVO_",
        extra="ignore",
    )

    service_name: str = "super-evo"
    port: int = 8090
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    redis_url: str = "redis://localhost:6379/5"
    db_url: str = "sqlite+aiosqlite:///./data/super_evo.db"

    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "super-evo"
    minio_secure: bool = False

    dvc_repo_path: Path = Field(default=Path("training"))
    dvc_remote_name: str = "minio"

    wandb_project: str = "diting-super-evo"
    wandb_entity: str | None = None
    wandb_mode: Literal["online", "offline", "disabled"] = "online"

    output_stream: str = "events:flywheel:lora_updated"

    @property
    def storage_root(self) -> Path:
        return self.dvc_repo_path / "data"


settings = SuperEvoSettings()
