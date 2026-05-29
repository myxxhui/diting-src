"""state-watch 配置.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class StateWatchSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="STATE_WATCH_", extra="ignore")

    service_name: str = "state-watch"
    port: int = 8003
    db_url: str = "sqlite+aiosqlite:///./data/state_watch.db"
    redis_url: str = "redis://localhost:6379/3"
    # D4 exit_engine 读 health_change 的 Redis DB（须与 EXIT_REDIS_URL 一致）
    exit_redis_url: str = "redis://localhost:6379/2"
    # health_change 发布到 D4 的 stream（同 exit_engine.config.health_change_stream）
    health_change_stream: str = "events:monitor:health_change"
    market_phase_change_stream: str = "events:monitor:market_phase_change"


settings = StateWatchSettings()
