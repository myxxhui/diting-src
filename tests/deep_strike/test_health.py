"""deep-strike 健康检查与骨架路由测试.

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from apps.deep_strike.config import settings
from apps.deep_strike.main import app


def test_health_returns_ok_with_upstream_keys() -> None:
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["service"] == "deep-strike"
        assert body["status"] in ("ok", "degraded")
        assert body["db"] in ("ok", "down")
        assert "upstream" in body
        for s in settings.upstream_streams:
            assert s in body["upstream"]
        assert body["weekly_quota"] == settings.weekly_thesis_quota


def test_list_playbooks_returns_profit_capture() -> None:
    with TestClient(app) as client:
        r = client.get("/api/playbooks")
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()["playbooks"]]
        assert "profit_capture" in ids


def test_scan_scaffold_requires_symbol() -> None:
    with TestClient(app) as client:
        r = client.post("/api/playbooks/profit_capture/scan", json={})
        assert r.status_code == 400


def test_scan_runs_profit_capture_playbook() -> None:
    with TestClient(app) as client:
        r = client.post("/api/playbooks/profit_capture/scan", json={"symbol": "600519"})
        assert r.status_code == 200
        body = r.json()
        assert body["symbol"] == "600519"
        assert body["decision"] in ("propose", "watch", "discard")
        assert "confidence" in body
        assert isinstance(body.get("signals"), list)
