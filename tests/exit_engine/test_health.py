"""健康检查测试.[Ref: step_01]"""
from __future__ import annotations

from fastapi.testclient import TestClient

from apps.exit_engine.main import app


def test_health_returns_ok() -> None:
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "exit-engine"
        assert body["output_stream"] == "events:exit:sell_signal"
        assert "protocols" in body
        for cls_name in [
            "StopLossProtocol",
            "TakeProfitProtocol",
            "ThesisInvalidProtocol",
            "RebalanceProtocol",
        ]:
            assert cls_name in body["protocols"]
            assert body["protocols"][cls_name] == "loaded"
        assert "upstream" in body
        assert "events:monitor:health_change" in body["upstream"]


def test_root_returns_doc_link() -> None:
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json() == {"service": "exit-engine", "doc": "/docs"}
