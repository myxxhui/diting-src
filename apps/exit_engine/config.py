"""exit-engine 配置中心。

[Ref: 03_/04_维度四/.../step_01]
[DNA: _System_DNA/04_exit_engine/dna_stage_1_启动期.yaml#tech_stack]
"""
from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class ExitEngineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="EXIT_", extra="ignore")

    service_name: str = "exit-engine"
    # 8090 由 super_evo 占用时默认 8092（可用 EXIT_PORT 覆盖）
    port: int = 8092
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    db_url: str = "sqlite+aiosqlite:///./data/exit_engine.db"
    db_url_sync: str = "sqlite:///./data/exit_engine.db"
    redis_url: str = "redis://localhost:6379/2"

    output_stream: str = "events:exit:sell_signal"
    health_change_stream: str = "events:monitor:health_change"

    sp1_stop_loss_threshold: float = -0.15
    sp1_stop_loss_priority: int = 1
    sp1_stop_loss_buffer_days: int = 0

    sp2_take_profit_threshold: float = 0.30
    sp2_take_profit_priority: int = 2
    sp2_take_profit_buffer_days: int = 3

    sp3_thesis_invalid_priority: int = 1
    sp3_thesis_invalid_buffer_days: int = 0

    sp4_rebalance_threshold: float = 0.25
    sp4_rebalance_priority: int = 3
    sp4_rebalance_buffer_days: int = 7

    sp5_financial_window_priority: int = 3
    sp5_financial_window_buffer_days: int = 0
    timer_signal_stream: str = "events:deep_strike:timer_signal"
    sp5_consumer_group: str = "dim_four_sp5"
    health_consumer_group: str = "dim_four"
    auto_consumer: bool = False

    quote_refresh_minutes: int = 30
    consumer_group: str = "exit_engine_consumer"


settings = ExitEngineSettings()
