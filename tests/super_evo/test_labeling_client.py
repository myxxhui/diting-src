"""Label Studio client / importer / exporter 契约测试（无真实容器）.

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_03_C2_Label_Studio部署.md]
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from apps.super_evo.labeling.client import LabelStudioClient, load_template
from apps.super_evo.labeling.exporter import export_to_verified_jsonl
from apps.super_evo.labeling.importer import jsonl_to_tasks


def test_templates_exist_and_have_decision_for_three_tasks():
    for name in ("financial_fraud", "shareholder", "related_party"):
        xml = load_template(name)
        assert "decision" in xml
        assert "<Choices" in xml
    assert "five_required" in load_template("thesis")
    assert "nli_label" in load_template("nli")


def test_jsonl_to_tasks_preserves_sample_id(tmp_path: Path):
    p = tmp_path / "demo.jsonl"
    lines = []
    for i in range(3):
        record = {
            "instruction": "inst",
            "input": f"in-{i}",
            "output": json.dumps({"decision": "pass"}),
            "metadata": {"sample_id": f"sid-{i}", "task_type": "financial_fraud", "batch_id": "B1"},
        }
        lines.append(json.dumps(record))
    p.write_text("\n".join(lines), encoding="utf-8")

    tasks = jsonl_to_tasks(p, "financial_fraud")
    assert len(tasks) == 3
    for i, t in enumerate(tasks):
        assert t["data"]["_sample_id"] == f"sid-{i}"
        assert t["data"]["_task_type"] == "financial_fraud"


class FakeLS:
    """避免真实 HTTP。"""

    def __init__(self, items: list[dict[str, Any]]):
        self.items = items

    def export_annotations(self, project_id: int, fmt: str = "JSON") -> list[dict[str, Any]]:
        return self.items


def test_export_to_verified_jsonl_writes_records(tmp_path: Path):
    fake_items = [
        {
            "data": {
                "input": "公司 X 财务数据...",
                "teacher_output": json.dumps({"decision": "degrade"}),
                "_sample_id": "sid-1",
                "_batch_id": "B1",
            },
            "created_at": "2026-05-16T08:00:00Z",
            "annotations": [
                {
                    "completed_by": {"email": "annotator1@diting.local"},
                    "result": [
                        {"from_name": "decision", "value": {"choices": ["reject"]}},
                        {"from_name": "risk_score", "value": {"rating": 9}},
                        {"from_name": "evidence", "value": {"text": ["e1", "e2"]}},
                        {"from_name": "notes", "value": {"text": ["人工修正后理由"]}},
                    ],
                }
            ],
        },
        {
            "data": {"input": "no annotation", "_sample_id": "sid-2"},
            "annotations": [],
        },
    ]
    client: Any = FakeLS(fake_items)
    out = tmp_path / "verified.jsonl"
    n = export_to_verified_jsonl(client, project_id=1, task_type="financial_fraud", output_path=out)
    assert n == 1
    record = json.loads(out.read_text().strip().splitlines()[0])
    assert record["metadata"]["verified"] is True
    assert record["metadata"]["verifier"] == "annotator1@diting.local"
    assert json.loads(record["output"])["decision"] == "reject"


def test_client_init_uses_env(monkeypatch):
    monkeypatch.setenv("SUPER_EVO_LS_URL", "http://example:8081")
    monkeypatch.setenv("SUPER_EVO_LS_USER_TOKEN", "tok-x")
    c = LabelStudioClient()
    assert c.base_url == "http://example:8081"
    assert c.token == "tok-x"
    c.close()
