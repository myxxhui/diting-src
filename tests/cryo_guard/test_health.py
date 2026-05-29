"""cryo-guard 健康检查测试。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from apps.cryo_guard.api.main import app
from apps.cryo_guard.config import settings


def test_root() -> None:
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["service"] == "cryo-guard"


def test_health_returns_ok() -> None:
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["service"] == settings.service_name
        # 三段必填
        for key in ("engines", "dependencies", "upstream_streams"):
            assert key in body, f"缺失字段：{key}"
        # 7 个上游流
        assert len(body["upstream_streams"]) == 7
        # 三引擎尚未加载
        for eng in ("financial_fraud", "shareholder_integrity", "related_party"):
            assert body["engines"][eng] == "not_loaded"


def test_decision_gate_health_initializing() -> None:
    with TestClient(app) as client:
        r = client.get("/api/decision-gate/health")
        assert r.status_code == 200
        assert r.json()["status"] == "initializing"
