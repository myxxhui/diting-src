"""super-evo 健康检查测试。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_01]
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.super_evo.main import app


def test_root_returns_service_name():
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        body = r.json()
        assert body["service"] == "super-evo"


def test_health_returns_components():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["service"] == "super-evo"
        assert "components" in body
        for key in ("redis", "minio", "dvc", "wandb"):
            assert key in body["components"]
        assert body["output_stream"] == "events:flywheel:lora_updated"


def test_health_status_field_is_ok_or_degraded():
    with TestClient(app) as client:
        r = client.get("/health")
        body = r.json()
        assert body["status"] in {"ok", "degraded"}
