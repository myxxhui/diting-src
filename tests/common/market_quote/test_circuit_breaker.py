"""断路器三态机测试。"""
from __future__ import annotations

from datetime import datetime, timedelta

from apps.common.market_quote.circuit_breaker import CircuitBreakerRegistry


def test_tripped_after_fail_threshold():
    reg = CircuitBreakerRegistry(fail_threshold=3, cool_down_sec=60)
    now = datetime(2026, 5, 23, 10, 0, 0)
    for _ in range(3):
        reg.record_failure("tencent", now)
    assert reg.can_execute("tencent", now) is False
    h = reg.health("tencent")
    assert h.status == "tripped"


def test_half_open_after_cooldown():
    reg = CircuitBreakerRegistry(fail_threshold=2, cool_down_sec=60)
    t0 = datetime(2026, 5, 23, 10, 0, 0)
    reg.record_failure("sina", t0)
    reg.record_failure("sina", t0)
    assert reg.can_execute("sina", t0) is False
    t1 = t0 + timedelta(seconds=61)
    assert reg.can_execute("sina", t1) is True
    assert reg.health("sina").status == "degraded"


def test_success_resets_breaker():
    reg = CircuitBreakerRegistry(fail_threshold=2, cool_down_sec=60)
    now = datetime(2026, 5, 23, 10, 0, 0)
    reg.record_failure("tencent", now)
    reg.record_success("tencent", now)
    assert reg.health("tencent").status == "ok"
    assert reg.health("tencent").consecutive_failures == 0
