"""Label Studio Webhook 路由单测.

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_03 §7.1]
"""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from apps.super_evo.db.database import get_engine, get_session
from apps.super_evo.db.models import LabelingRecord
from apps.super_evo.main import app


@pytest.fixture(autouse=True)
def _seed_labeling():
    """每个测试前插入 1 条 labeling 记录，测试后清理。"""
    get_engine()
    session = get_session()
    rec = LabelingRecord(
        batch_date="20260523",
        dimension="cryo",
        sample_id="test-sample-1",
        task_type="financial_fraud",
        ls_project_id=1,
        ls_task_id=101,
        status="imported",
    )
    session.add(rec)
    session.commit()
    rec_id = rec.id
    session.close()
    yield
    session2 = get_session()
    session2.query(LabelingRecord).filter(LabelingRecord.id == rec_id).delete()
    session2.commit()
    session2.close()


def _build_payload(action: str = "ANNOTATION_CREATED", result: list | None = None) -> dict:
    return {
        "action": action,
        "annotation": {
            "id": 999,
            "task": 101,
            "result": result if result is not None else [{"from_name": "label", "value": {"choices": ["财务欺诈"]}}],
        },
        "project": {"id": 1},
    }


def _sig(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestLsWebhook:
    def test_annotation_created_updates_status(self, monkeypatch):
        monkeypatch.setattr("apps.super_evo.api.routes.labeling._WEBHOOK_SECRET", "")
        client = TestClient(app)
        payload = _build_payload("ANNOTATION_CREATED")
        r = client.post(
            "/api/labeling/ls_webhook",
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["new_status"] == "verified"
        assert body["updated_rows"] == 1

    def test_annotation_deleted_marks_deleted(self, monkeypatch):
        monkeypatch.setattr("apps.super_evo.api.routes.labeling._WEBHOOK_SECRET", "")
        client = TestClient(app)
        payload = _build_payload("ANNOTATION_DELETED", result=[])
        r = client.post(
            "/api/labeling/ls_webhook",
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200
        assert r.json()["new_status"] == "deleted"

    def test_non_annotation_event_ignored(self, monkeypatch):
        monkeypatch.setattr("apps.super_evo.api.routes.labeling._WEBHOOK_SECRET", "")
        client = TestClient(app)
        payload = {"action": "PROJECT_CREATED", "project": {"id": 1}}
        r = client.post(
            "/api/labeling/ls_webhook",
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200
        assert r.json()["handled"] is False

    def test_hmac_valid_signature_accepted(self, monkeypatch):
        secret = "my-secret-123"
        monkeypatch.setattr("apps.super_evo.api.routes.labeling._WEBHOOK_SECRET", secret)
        client = TestClient(app)
        payload = _build_payload()
        body = json.dumps(payload).encode()
        sig = _sig(body, secret)
        r = client.post(
            "/api/labeling/ls_webhook",
            content=body,
            headers={"Content-Type": "application/json", "X-LSE-Signature": sig},
        )
        assert r.status_code == 200

    def test_hmac_wrong_signature_rejected(self, monkeypatch):
        secret = "my-secret-123"
        monkeypatch.setattr("apps.super_evo.api.routes.labeling._WEBHOOK_SECRET", secret)
        client = TestClient(app)
        payload = _build_payload()
        body = json.dumps(payload).encode()
        r = client.post(
            "/api/labeling/ls_webhook",
            content=body,
            headers={"Content-Type": "application/json", "X-LSE-Signature": "bad-sig"},
        )
        assert r.status_code == 401

    def test_empty_result_yields_pending_review(self, monkeypatch):
        monkeypatch.setattr("apps.super_evo.api.routes.labeling._WEBHOOK_SECRET", "")
        client = TestClient(app)
        payload = _build_payload("ANNOTATION_CREATED", result=[])
        r = client.post(
            "/api/labeling/ls_webhook",
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200
        assert r.json()["new_status"] == "pending_review"
