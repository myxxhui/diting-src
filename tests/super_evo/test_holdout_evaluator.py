"""Holdout 评测器 + RegressionGate 单元测试（≥10 项）。

不依赖 GPU / vLLM / DB。

[Ref: step_05 §7.1-H：≥10 pytest；E1-E4、C1-C4]
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.super_evo.quality.holdout_evaluator import (
    HoldoutEvaluator,
    MetricsResult,
    _check_regression,
    _extract_label,
    _flip_label,
    compute_metrics,
    load_holdout_cases,
    locate_holdout,
    run_inference,
    InferenceResult,
)
from apps.super_evo.quality.regression_gate import (
    GateResult,
    apply_regression_gate,
    manual_override_gate,
)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _write_holdout(tmp_path: Path, dim: str, n: int, label_ratio: float = 0.5) -> Path:
    """生成 holdout jsonl 用于测试。"""
    out_dir = tmp_path / dim
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "holdout.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for i in range(n):
            label = "pass" if i / n < label_ratio else "block"
            rec = {
                "instruction": "判断",
                "input": f"输入-{i}",
                "output": json.dumps({"label": label}, ensure_ascii=False),
                "metadata": {"sample_id": f"{dim}_h_{i:04d}", "verified": True},
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


# ---------------------------------------------------------------------------
# Test: locate_holdout
# ---------------------------------------------------------------------------


def test_locate_holdout_found(tmp_path: Path):
    _write_holdout(tmp_path, "cryo", 10)
    path = locate_holdout("cryo", holdout_root=tmp_path)
    assert path.exists()


def test_locate_holdout_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Holdout 不存在"):
        locate_holdout("cryo", holdout_root=tmp_path)


# ---------------------------------------------------------------------------
# Test: load_holdout_cases
# ---------------------------------------------------------------------------


def test_load_holdout_cases_count(tmp_path: Path):
    path = _write_holdout(tmp_path, "thrust", 30)
    cases = load_holdout_cases(path)
    assert len(cases) == 30


def test_load_holdout_cases_fields(tmp_path: Path):
    path = _write_holdout(tmp_path, "thrust", 5)
    cases = load_holdout_cases(path)
    assert all("instruction" in c for c in cases)
    assert all("metadata" in c for c in cases)


# ---------------------------------------------------------------------------
# Test: _extract_label / _flip_label
# ---------------------------------------------------------------------------


def test_extract_label_from_json_output():
    case = {"output": json.dumps({"label": "pass"})}
    assert _extract_label(case) == "pass"


def test_extract_label_from_decision():
    case = {"output": json.dumps({"decision": "block"})}
    assert _extract_label(case) == "block"


def test_flip_label_binary():
    assert _flip_label("pass") == "block"
    assert _flip_label("block") == "pass"


# ---------------------------------------------------------------------------
# Test: run_inference (mock)
# ---------------------------------------------------------------------------


def test_run_inference_mock_returns_correct_count(tmp_path: Path):
    path = _write_holdout(tmp_path, "cryo", 20)
    cases = load_holdout_cases(path)
    results = run_inference(cases, mode="mock", seed=42)
    assert len(results) == 20


def test_run_inference_mock_high_accuracy(tmp_path: Path):
    """mock 推理：90% 准确率（测试整体准确率 ≥ 75%）。"""
    path = _write_holdout(tmp_path, "cryo", 100)
    cases = load_holdout_cases(path)
    results = run_inference(cases, mode="mock", seed=42)
    correct = sum(1 for r in results if r.prediction == r.label)
    assert correct >= 70, f"mock 准确率应 ≥70%，实际 {correct/100:.0%}"


def test_run_inference_mock_reproducible(tmp_path: Path):
    """E3: 同 seed 结果相同（可复现）。"""
    path = _write_holdout(tmp_path, "cryo", 20)
    cases = load_holdout_cases(path)
    r1 = run_inference(cases, mode="mock", seed=123)
    r2 = run_inference(cases, mode="mock", seed=123)
    assert [x.prediction for x in r1] == [x.prediction for x in r2]


def test_run_inference_vllm_no_url_raises():
    """mode=vllm 且 vllm_url=None → 抛 ValueError（DECISION_PENDING 提示）。"""
    with pytest.raises(ValueError, match="DECISION_PENDING"):
        run_inference([], mode="vllm", vllm_url=None)


# ---------------------------------------------------------------------------
# Test: compute_metrics
# ---------------------------------------------------------------------------


def test_compute_metrics_perfect(tmp_path: Path):
    results = [InferenceResult(sample_id=f"s{i}", prediction="pass", label="pass") for i in range(10)]
    metrics = compute_metrics(results)
    assert metrics.recall == pytest.approx(1.0)
    assert metrics.precision == pytest.approx(1.0)
    assert metrics.f1 == pytest.approx(1.0)


def test_compute_metrics_empty():
    metrics = compute_metrics([])
    assert metrics.n_cases == 0
    assert metrics.recall == 0.0


def test_compute_metrics_per_class(tmp_path: Path):
    results = [
        InferenceResult("a", "pass", "pass"),
        InferenceResult("b", "block", "block"),
        InferenceResult("c", "pass", "block"),
    ]
    m = compute_metrics(results)
    assert "pass" in m.per_class
    assert "block" in m.per_class


# ---------------------------------------------------------------------------
# Test: HoldoutEvaluator（mock 模式）
# ---------------------------------------------------------------------------


def test_holdout_evaluator_first_run(tmp_path: Path):
    """首次评测（无 baseline）→ is_first_run=True，blocked=False。"""
    _write_holdout(tmp_path, "cryo", 50)
    evaluator = HoldoutEvaluator(dim="cryo", lora_version_id=1, holdout_root=tmp_path, mode="mock")
    report = evaluator.evaluate()
    assert report.is_first_run is True
    assert report.blocked is False
    assert report.n_cases == 50
    assert report.inference_mode == "mock"


def test_holdout_evaluator_blocked_on_vllm_no_url(tmp_path: Path):
    """mode=vllm 但无 vllm_url → inference_mode=BLOCKED（no-mock-policy N1）。"""
    _write_holdout(tmp_path, "thrust", 30)
    evaluator = HoldoutEvaluator(
        dim="thrust", lora_version_id=2, holdout_root=tmp_path, mode="vllm", vllm_url=None
    )
    report = evaluator.evaluate()
    assert report.inference_mode == "BLOCKED"
    assert report.blocked is True


def test_holdout_evaluator_file_not_found(tmp_path: Path):
    evaluator = HoldoutEvaluator(dim="cryo", lora_version_id=1, holdout_root=tmp_path, mode="mock")
    with pytest.raises(FileNotFoundError):
        evaluator.evaluate()


# ---------------------------------------------------------------------------
# Test: _check_regression
# ---------------------------------------------------------------------------


def test_check_regression_no_regression():
    current = MetricsResult(recall=0.92, precision=0.91, f1=0.91, n_cases=50)
    baseline = MetricsResult(recall=0.90, precision=0.90, f1=0.90, n_cases=50)
    blocked, reason = _check_regression(current, baseline, threshold=0.05)
    assert blocked is False


def test_check_regression_recall_exceeds_threshold():
    current = MetricsResult(recall=0.80, precision=0.90, f1=0.85, n_cases=50)
    baseline = MetricsResult(recall=0.92, precision=0.90, f1=0.91, n_cases=50)
    blocked, reason = _check_regression(current, baseline, threshold=0.05)
    assert blocked is True
    assert reason is not None and "recall" in reason


# ---------------------------------------------------------------------------
# Test: RegressionGate
# ---------------------------------------------------------------------------


def test_apply_regression_gate_first_run():
    """无 baseline → Pass（首次运行）。"""
    gate = apply_regression_gate(0.85, 0.83, 0.84, None, None, None)
    assert gate.blocked is False
    assert gate.delta_recall is None


def test_apply_regression_gate_pass():
    gate = apply_regression_gate(0.91, 0.90, 0.90, 0.90, 0.89, 0.89)
    assert gate.blocked is False


def test_apply_regression_gate_blocked():
    """recall 退化 11.1%（超 5%）→ blocked=True。"""
    gate = apply_regression_gate(0.80, 0.88, 0.84, 0.90, 0.89, 0.89)
    assert gate.blocked is True
    assert gate.block_reason is not None


def test_regression_gate_exit_code_simulation():
    """模拟 CI：blocked=True → 应 exit 1。"""
    gate = apply_regression_gate(0.80, 0.82, 0.81, 0.90, 0.88, 0.89)
    ci_exit = 1 if gate.blocked else 0
    assert ci_exit == 1


# ---------------------------------------------------------------------------
# Test: manual_override_gate
# ---------------------------------------------------------------------------


def test_manual_override_gate_valid_adr():
    result = manual_override_gate(42, "arch_zhang", "ADR-2026-05-01")
    assert result["blocked"] is False
    assert result["override"] is True


def test_manual_override_gate_invalid_adr():
    """缺 ADR 前缀 → 抛 ValueError（C3：不可无 ADR 旁路）。"""
    with pytest.raises(ValueError, match="ADR-"):
        manual_override_gate(42, "arch_zhang", "no-adr-ref")


# ---------------------------------------------------------------------------
# Test: generate_holdout_data（扩标注）
# ---------------------------------------------------------------------------


def test_generate_holdout_produces_correct_count(tmp_path: Path):
    from scripts.generate_holdout_data import generate_holdout, write_holdout

    cases = generate_holdout("cryo", 50)
    assert len(cases) == 50
    path = write_holdout("cryo", cases, tmp_path)
    n = sum(1 for _ in path.open(encoding="utf-8") if _.strip())
    assert n == 50


def test_generate_holdout_labels_balanced(tmp_path: Path):
    from scripts.generate_holdout_data import generate_holdout

    cases = generate_holdout("thrust", 30)
    labels = [json.loads(c["output"])["label"] for c in cases]
    pass_cnt = labels.count("pass")
    block_cnt = labels.count("block")
    assert pass_cnt > 0 and block_cnt > 0, "holdout 标签应包含 pass 和 block"


def test_generate_holdout_verified_flag(tmp_path: Path):
    from scripts.generate_holdout_data import generate_holdout

    cases = generate_holdout("narrative", 30)
    assert all(c["metadata"]["verified"] is True for c in cases)
    assert all(c["metadata"]["holdout_locked"] is True for c in cases)
