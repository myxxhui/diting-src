"""Copilot 配置中心。

[Ref: 03_/00_维度零/.../step_01]
[Ref: 03_/00_维度零/.../step_05 告警通道]
[Ref: 03_/00_维度零/.../step_06 M4 价值账本]
[DNA: _System_DNA/00_co_pilot/dna_stage_1_启动期.yaml#tech_stack]
"""
from __future__ import annotations

from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class CopilotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="COPILOT_")

    service_name: str = "copilot"
    port: int = 8080
    db_url: str = "sqlite+aiosqlite:///./data/copilot.db"
    redis_url: str = "redis://localhost:6379/0"

    upstream_streams: List[str] = [
        "events:cryo_guard:reject",
        "events:cryo_guard:degrade",
        "events:cryo_guard:pass",
        "events:thrust:thesis_proposed",
        "events:monitor:health_change",
        "events:exit:sell_signal",
        "events:flywheel:lora_updated",
    ]

    wechat_webhook: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    smtp_host: str = "smtp.resend.com"
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: str = "copilot@example.com"
    smtp_to: Optional[str] = None
    alert_dedup_window: int = 3600
    alert_red_sla: int = 300
    alert_consumer_enabled: bool = True

    ledger_reports_dir: str = "./data/reports"
    circuit_window: int = 20
    circuit_bh_threshold: float = 0.35
    monthly_cron_day: int = 1
    monthly_cron_hour: int = 9
    ledger_scheduler_enabled: bool = True


settings = CopilotSettings()
