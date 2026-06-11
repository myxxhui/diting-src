"""AIDispatcher 单测。

[Ref: 03_原子目标与规约/_共享规约/19_异构AI调度栈规约.md §七]
"""
from __future__ import annotations

import pytest

from apps.common.ai_dispatcher import (
    AIDispatcher,
    AIResponse,
    BudgetExceededError,
    Route,
    anthropic_read_timeout_sec,
    anthropic_use_streaming,
    is_transient_anthropic_error,
    probe_anthropic_proxy_tcp,
    _parse_proxy_host_port,
)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def make_dispatcher(**kw) -> AIDispatcher:
    return AIDispatcher(anthropic_key="", budget_yuan_daily=kw.pop("budget", 100.0), **kw)


MESSAGES = [{"role": "user", "content": "只回复 OK"}]


# ---------------------------------------------------------------------------
# T1: mock 路由（无 key）
# ---------------------------------------------------------------------------

def test_anthropic_read_timeout_t2_16k():
    assert anthropic_read_timeout_sec(scene="radar_assess", max_tokens=16_384) == 900.0


def test_anthropic_use_streaming_t2_large():
    assert anthropic_use_streaming(scene="radar_assess", max_tokens=4096) is True
    assert anthropic_use_streaming(scene="radar_assess", max_tokens=2048) is False
    assert anthropic_use_streaming(scene="critic", max_tokens=8192) is False


def test_anthropic_use_streaming_disabled_via_proxy(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_HTTPS_PROXY", "http://127.0.0.1:3128")
    assert anthropic_use_streaming(scene="radar_assess", max_tokens=16_384) is False
    monkeypatch.setenv("ANTHROPIC_FORCE_STREAMING", "1")
    assert anthropic_use_streaming(scene="radar_assess", max_tokens=16_384) is True


def test_is_transient_anthropic_error_chunked():
    assert is_transient_anthropic_error(
        RuntimeError(
            "peer closed connection without sending complete message body "
            "(incomplete chunked read)"
        )
    )
    assert not is_transient_anthropic_error(RuntimeError("401 invalid x-api-key"))


def test_parse_proxy_host_port():
    assert _parse_proxy_host_port("http://user:pass@47.237.76.203:3128") == (
        "47.237.76.203",
        3128,
    )
    assert _parse_proxy_host_port("") is None


def test_probe_anthropic_proxy_tcp_no_proxy(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_HTTPS_PROXY", raising=False)
    ok, detail = probe_anthropic_proxy_tcp()
    assert ok is True
    assert detail == "direct"


def test_probe_anthropic_proxy_tcp_unreachable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_HTTPS_PROXY", "http://127.0.0.1:31999")
    ok, detail = probe_anthropic_proxy_tcp(timeout_sec=0.5)
    assert ok is False
    assert "sync-anthropic-proxy-to-copilot" in detail


def test_call_mock_no_key():
    d = make_dispatcher()
    r = d.call("dry_run", MESSAGES)
    assert isinstance(r, AIResponse)
    assert r.route == "mock"
    assert r.model == "mock"
    assert "_dispatcher_mock" in r.text


# ---------------------------------------------------------------------------
# T2: remote 降级 → mock（无 key）
# ---------------------------------------------------------------------------

def test_remote_degrades_to_mock_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    d = AIDispatcher(anthropic_key="", budget_yuan_daily=100.0)
    r = d.call("critic", MESSAGES)
    assert r.route == "remote"          # route 字段仍标记 remote（意图路由）
    assert r.model == "mock"           # 但实际降级到 mock


# ---------------------------------------------------------------------------
# T3: local 降级 → mock（vLLM 未起）
# ---------------------------------------------------------------------------

def test_local_degrades_to_mock():
    d = make_dispatcher(vllm_base_url="http://127.0.0.1:19999/v1")
    r = d.call("etl", MESSAGES)
    assert r.route == "local"
    assert r.model == "mock"           # vLLM 不可达 → mock


# ---------------------------------------------------------------------------
# T4: 场景路由映射
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scene,expected_route", [
    ("scorer_policy", "remote"),
    ("scorer_mapping", "remote"),
    ("critic", "remote"),
    ("architect", "remote"),
    ("timer", "remote"),
    ("etl", "local"),
    ("dry_run", "mock"),
])
def test_scene_route_mapping(scene, expected_route: Route):
    from apps.common.ai_dispatcher import _SCENE_ROUTE
    assert _SCENE_ROUTE[scene] == expected_route


# ---------------------------------------------------------------------------
# T5: force_route 覆盖
# ---------------------------------------------------------------------------

def test_force_route_mock():
    d = make_dispatcher()
    r = d.call("critic", MESSAGES, force_route="mock")
    assert r.route == "mock"
    assert r.model == "mock"


# ---------------------------------------------------------------------------
# T6: 预算守门
# ---------------------------------------------------------------------------

def test_budget_guard():
    d = AIDispatcher(anthropic_key="", budget_yuan_daily=0.0)
    d._daily_spent = 1.0   # 模拟已超出
    import time
    d._daily_date = time.strftime("%Y-%m-%d")
    with pytest.raises(BudgetExceededError):
        d.call("critic", MESSAGES)


# ---------------------------------------------------------------------------
# T7: budget_status
# ---------------------------------------------------------------------------

def test_budget_status_fresh():
    d = make_dispatcher(budget=50.0)
    s = d.budget_status()
    assert s["ok"] is True
    assert s["limit_yuan"] == 50.0
    assert s["spent_yuan"] == 0.0


# ---------------------------------------------------------------------------
# T8: 真实 Anthropic（仅 key 存在时执行，CI 可跳过）
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not __import__("os").getenv("ANTHROPIC_API_KEY"),
    reason="需要 ANTHROPIC_API_KEY",
)
def test_call_remote_real():
    import os
    d = AIDispatcher(
        anthropic_key=os.environ["ANTHROPIC_API_KEY"],
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6"),
    )
    r = d.call("critic", [{"role": "user", "content": "只回复 OK"}], max_tokens=16)
    assert r.route == "remote"
    assert r.model != "mock"
    assert "OK" in r.text or len(r.text) > 0
    assert r.latency_ms > 0
