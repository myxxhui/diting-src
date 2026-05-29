"""训练流水线单元/契约测试。

不要求 GPU；不要求 llamafactory-cli；用 --dry-run 路径校验所有产物形态。
[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_04_C3_LLaMA_Factory训练流水线.md]
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.super_evo.events.training_complete import TrainingCompletedEvent
from apps.super_evo.training.data_prep import register_dataset_info, split_verified_jsonl
from apps.super_evo.training.gpu_check import check_gpu
from apps.super_evo.training.trainer import TrainRequest, render_config, run_training


def _make_jsonl(p: Path, n: int, verified: bool) -> Path:
    lines = []
    for i in range(n):
        rec = {
            "instruction": "请分析",
            "input": f"input-{i}",
            "output": json.dumps({"decision": "pass", "risk_score": 0.1}, ensure_ascii=False),
            "metadata": {"verified": verified, "task_type": "financial_fraud", "sample_id": f"s{i}"},
        }
        lines.append(json.dumps(rec, ensure_ascii=False))
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def test_split_requires_verified_by_default(tmp_path: Path):
    src = _make_jsonl(tmp_path / "in.jsonl", n=20, verified=False)
    with pytest.raises(ValueError):
        split_verified_jsonl(src, tmp_path / "out", "financial_fraud")


def test_split_writes_three_files_and_info(tmp_path: Path):
    src = _make_jsonl(tmp_path / "in.jsonl", n=50, verified=True)
    out = tmp_path / "out"
    r = split_verified_jsonl(src, out, "financial_fraud")
    assert r.n_train + r.n_val + r.n_test == 50
    assert (out / "financial_fraud_train.json").exists()
    assert (out / "financial_fraud_val.json").exists()
    assert (out / "financial_fraud_test.json").exists()
    info = json.loads((out / "dataset_info.json").read_text())
    assert "financial_fraud_train" in info


def test_split_allows_unverified_when_flagged(tmp_path: Path):
    src = _make_jsonl(tmp_path / "in.jsonl", n=20, verified=False)
    r = split_verified_jsonl(src, tmp_path / "out", "financial_fraud", require_verified=False)
    assert r.n_train >= 1


def test_render_config_substitutes_placeholders(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    req = TrainRequest(
        lora_name="demo_lora",
        task="financial_fraud",
        base_model="models/Qwen2.5-1.5B-Instruct",
        rank=32,
        epochs=2,
        max_steps=10,
    )
    cfg = render_config(req)
    text = cfg.read_text()
    assert "lora_rank: 32" in text
    assert "lora_alpha: 64" in text
    assert "models/Qwen2.5-1.5B-Instruct" in text
    assert "max_steps: 10" in text
    assert "${LORA_NAME}" not in text


def test_run_training_dry_run_writes_artifacts(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    req = TrainRequest(lora_name="sanity_v0", task="financial_fraud", rank=16)
    result = run_training(req, dry_run=True)
    assert result.return_code == 0
    assert result.adapter_path is not None and result.adapter_path.exists()
    assert result.metrics_path is not None and result.metrics_path.exists()
    metrics = json.loads(result.metrics_path.read_text())
    assert metrics["dry_run"] is True


def test_check_gpu_returns_structured_info():
    info = check_gpu(min_free_mib=18_000)
    assert hasattr(info, "available")
    assert isinstance(info.names, list)


def test_training_event_serializes():
    event = TrainingCompletedEvent(
        lora_name="x",
        lora_version="v1",
        base_model="m",
        rank=16,
        dataset_path="d.jsonl",
        metrics={"final_train_loss": 0.4},
        output_path="output/x",
        config_path="output/x/train_config.yaml",
    )
    msg = event.to_message()
    payload = json.loads(msg["data"])
    assert payload["event_type"] == "training_completed"
    assert payload["lora_name"] == "x"


def test_register_dataset_info_idempotent(tmp_path: Path):
    p = register_dataset_info(tmp_path, "financial_fraud")
    register_dataset_info(tmp_path, "shareholder")
    info = json.loads(p.read_text())
    assert "financial_fraud_train" in info and "shareholder_train" in info
