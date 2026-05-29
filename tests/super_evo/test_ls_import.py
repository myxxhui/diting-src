"""ls_import 脚本 + labelings ORM 契约测试."""
from __future__ import annotations

import json
from pathlib import Path

from apps.super_evo.db.database import get_engine, get_session
from apps.super_evo.db.models import LabelingRecord
from apps.super_evo.labeling.importer import jsonl_to_tasks


def test_labelings_table_created():
    get_engine()
    session = get_session()
    try:
        n = session.query(LabelingRecord).count()
        assert n >= 0
    finally:
        session.close()


def test_jsonl_to_tasks_from_sanity_fixture():
    p = Path("training/data/distilled/financial_fraud/sanity_dry_run.jsonl")
    if not p.exists():
        return
    tasks = jsonl_to_tasks(p, "financial_fraud")
    assert len(tasks) >= 1
    assert "_sample_id" in tasks[0]["data"]


def test_persist_labeling_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPER_EVO_DB_URL", f"sqlite:///{tmp_path}/test.db")
    from importlib import reload

    import apps.super_evo.config as cfg
    import apps.super_evo.db.database as db

    reload(cfg)
    reload(db)

    p = tmp_path / "demo.jsonl"
    rec = {
        "instruction": "x",
        "input": "in",
        "output": json.dumps({"decision": "pass"}),
        "metadata": {"sample_id": "s-demo", "task_type": "financial_fraud"},
    }
    p.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    tasks = jsonl_to_tasks(p, "financial_fraud")
    session = db.get_session()
    try:
        data = tasks[0]["data"]
        row = LabelingRecord(
            batch_date="20260523",
            dimension="cryo",
            sample_id=data["_sample_id"],
            task_type="financial_fraud",
            status="imported",
            payload_json=json.dumps(data),
        )
        session.add(row)
        session.commit()
        got = session.query(LabelingRecord).filter_by(sample_id=data["_sample_id"]).one()
        assert got.dimension == "cryo"
    finally:
        session.close()
