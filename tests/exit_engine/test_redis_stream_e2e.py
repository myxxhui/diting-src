"""Redis 真流消费器集成测试（需 REDIS_URL 可达）。"""
from __future__ import annotations

import os

import pytest

from apps.exit_engine.db.init_db import init
from apps.exit_engine.events.redis_runner import ExitStreamRedisRunner
from apps.exit_engine.services.stream_consumer import (
    HEALTH_CHANGE_STREAM,
    HEALTH_CONSUMER_GROUP,
    SP5_CONSUMER_GROUP,
    TIMER_SIGNAL_STREAM,
)
from tests.fixtures.inject_health_change import inject_health_change
from tests.fixtures.inject_timer_signal import inject_timer_signal


@pytest.fixture
def redis_url() -> str:
    url = os.environ.get("REDIS_URL", "redis://8.217.158.218:30379/0")
    runner = ExitStreamRedisRunner(url)
    try:
        runner.ping()
    except Exception as exc:
        pytest.skip(f"Redis 不可用: {exc}")
    return url


@pytest.fixture
def runner(redis_url: str) -> ExitStreamRedisRunner:
    init()
    r = ExitStreamRedisRunner(redis_url)
    r.ensure_all_groups()
    return r


def test_redis_sp3_xreadgroup(runner: ExitStreamRedisRunner, redis_url: str) -> None:
    inject_health_change(redis_url, symbol="002837", new_state="exit")
    results = runner.poll_once(
        HEALTH_CHANGE_STREAM, HEALTH_CONSUMER_GROUP, consumer_name="pytest_sp3"
    )
    assert any(r.protocol == "SP3" and r.handled for r in results)


def test_redis_sp5_xreadgroup(runner: ExitStreamRedisRunner, redis_url: str) -> None:
    inject_timer_signal(redis_url, symbol="300308", stage="retreat")
    results = runner.poll_once(
        TIMER_SIGNAL_STREAM, SP5_CONSUMER_GROUP, consumer_name="pytest_sp5"
    )
    assert any(r.protocol == "SP5" and r.triggered for r in results)
