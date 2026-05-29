"""Holdout 评测器 — per-dim 评测 recall/precision/f1，对比 prod baseline。

不依赖 GPU：mock 推理模式供本地/CI 开发使用；真实推理需 vLLM（DECISION_PENDING：GPU）。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_05_Holdout评测器与CI_Block.md §7.1-A/B]
"""

from __future__ import annotations

import json
import logging
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Holdout 数据加载
# ---------------------------------------------------------------------------

HOLDOUT_ROOT = Path("training/data/holdout")  # 相对工作目录；可由 env 覆盖


def locate_holdout(dim: str, holdout_root: Path | None = None) -> Path:
    """返回指定维度的 holdout jsonl 路径。

    约定路径：{holdout_root}/{dim}/holdout.jsonl
    """
    root = holdout_root or HOLDOUT_ROOT
    candidate = root / dim / "holdout.jsonl"
    if not candidate.exists():
        raise FileNotFoundError(f"Holdout 不存在：{candidate}（H3/H4 准出要求）")
    return candidate


def load_holdout_cases(path: Path) -> list[dict]:
    """加载 holdout jsonl，每行一个 case。"""
    cases = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning("holdout 第%d行解析失败: %s", lineno, e)
    return cases


# ---------------------------------------------------------------------------
# 推理接口（mock / vLLM）
# ---------------------------------------------------------------------------


@dataclass
class InferenceResult:
    sample_id: str
    prediction: str  # 模型输出原始文本
    label: str       # ground-truth label


def _mock_infer(case: dict, seed: int = 42) -> str:
    """Mock 推理：以 90% 概率返回正确答案，模拟基础性能。不调用任何模型。"""
    rng = random.Random(seed ^ hash(case.get("input", "")))
    gt = _extract_label(case)
    return gt if rng.random() < 0.90 else _flip_label(gt)


def _extract_label(case: dict) -> str:
    """从 case 中提取 ground-truth label。"""
    output = case.get("output", "")
    if isinstance(output, str):
        try:
            d = json.loads(output)
            if "label" in d:
                return str(d["label"])
            if "decision" in d:
                return str(d["decision"])
        except json.JSONDecodeError:
            pass
        return output.strip()
    if isinstance(output, dict):
        return str(output.get("label", output.get("decision", "unknown")))
    return str(output)


def _flip_label(label: str) -> str:
    """翻转二分类 label（用于 mock 错误注入）。"""
    mapping = {"pass": "block", "block": "pass", "yes": "no", "no": "yes"}
    return mapping.get(label.lower(), f"not_{label}")


def run_inference(
    cases: list[dict],
    adapter_path: Optional[str] = None,
    vllm_url: Optional[str] = None,
    mode: str = "mock",
    seed: int = 42,
) -> list[InferenceResult]:
    """批量推理。

    mode="mock"  → mock 推理（不需要 GPU）
    mode="vllm"  → 调用 vLLM HTTP API（DECISION_PENDING：需 GPU 环境）
    """
    if mode == "vllm":
        if not vllm_url:
            raise ValueError(
                "DECISION_PENDING: vLLM 推理需要 vllm_url 且 GPU 环境；"
                "当前缺少 vllm_url，无法执行真实推理。"
                "请确认 GPU 环境后再执行 make evo-step05-evaluate-*"
            )
        return _vllm_infer(cases, vllm_url, adapter_path)

    logger.info("使用 mock 推理（seed=%d，n=%d）", seed, len(cases))
    return [
        InferenceResult(
            sample_id=c.get("metadata", {}).get("sample_id", f"case_{i}"),
            prediction=_mock_infer(c, seed=seed + i),
            label=_extract_label(c),
        )
        for i, c in enumerate(cases)
    ]


def _vllm_infer(
    cases: list[dict], vllm_url: str, adapter_path: Optional[str]
) -> list[InferenceResult]:  # pragma: no cover
    """真实 vLLM 推理（需 GPU）。DECISION_PENDING。"""
    try:
        import httpx
    except ImportError as e:
        raise RuntimeError("vLLM 推理需要 httpx，请 pip install httpx") from e

    results = []
    with httpx.Client(timeout=60.0) as client:
        for i, case in enumerate(cases):
            payload = {
                "model": adapter_path or "default",
                "prompt": f"{case.get('instruction','')}\n{case.get('input','')}",
                "max_tokens": 256,
            }
            resp = client.post(f"{vllm_url}/v1/completions", json=payload)
            resp.raise_for_status()
            text = resp.json()["choices"][0]["text"].strip()
            prediction = _extract_label({"output": text})
            results.append(
                InferenceResult(
                    sample_id=case.get("metadata", {}).get("sample_id", f"case_{i}"),
                    prediction=prediction,
                    label=_extract_label(case),
                )
            )
    return results


# ---------------------------------------------------------------------------
# 指标计算
# ---------------------------------------------------------------------------


@dataclass
class MetricsResult:
    recall: float
    precision: float
    f1: float
    n_cases: int
    per_class: dict[str, dict[str, float]] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "recall": self.recall,
            "precision": self.precision,
            "f1": self.f1,
            "n_cases": self.n_cases,
            "per_class": self.per_class,
        }


def compute_metrics(results: list[InferenceResult]) -> MetricsResult:
    """计算 macro recall/precision/f1（与 baseline 对比用）。

    E2 要求：per-class + macro；E3 要求：同 seed 可复现 ±1e-4。
    """
    if not results:
        return MetricsResult(recall=0.0, precision=0.0, f1=0.0, n_cases=0)

    labels = sorted({r.label for r in results})
    per_class: dict[str, dict[str, float]] = {}

    for label in labels:
        tp = sum(1 for r in results if r.label == label and r.prediction == label)
        fn = sum(1 for r in results if r.label == label and r.prediction != label)
        fp = sum(1 for r in results if r.label != label and r.prediction == label)

        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        per_class[label] = {"recall": rec, "precision": prec, "f1": f1, "tp": tp, "fn": fn, "fp": fp}

    macro_recall = sum(v["recall"] for v in per_class.values()) / len(per_class)
    macro_prec = sum(v["precision"] for v in per_class.values()) / len(per_class)
    macro_f1 = sum(v["f1"] for v in per_class.values()) / len(per_class)

    return MetricsResult(
        recall=round(macro_recall, 6),
        precision=round(macro_prec, 6),
        f1=round(macro_f1, 6),
        n_cases=len(results),
        per_class=per_class,
    )


# ---------------------------------------------------------------------------
# HoldoutEvaluator 主类
# ---------------------------------------------------------------------------


@dataclass
class EvaluationReport:
    dim: str
    lora_version_id: int
    metrics: MetricsResult
    baseline_metrics: Optional[MetricsResult]
    baseline_lora_version_id: Optional[int]
    blocked: bool
    block_reason: Optional[str]
    is_first_run: bool
    inference_mode: str  # mock | vllm | BLOCKED
    holdout_path: str
    n_cases: int


class HoldoutEvaluator:
    """Holdout 评测器。

    [Ref: step_05 §7.1-A/B]

    使用方式：
        evaluator = HoldoutEvaluator(dim="cryo", lora_version_id=1)
        report = evaluator.evaluate(adapter_path="output/sanity_v0/...")
    """

    # 退化阈值：任一指标 (new-old)/old < -REGRESSION_THRESHOLD 则 block
    REGRESSION_THRESHOLD = 0.05  # 可通过 yaml 覆盖，见 regression_gate.py

    def __init__(
        self,
        dim: str,
        lora_version_id: int,
        holdout_root: Path | None = None,
        vllm_url: Optional[str] = None,
        mode: str = "mock",
        seed: int = 42,
    ) -> None:
        self.dim = dim
        self.lora_version_id = lora_version_id
        self.holdout_root = holdout_root
        self.vllm_url = vllm_url
        self.mode = mode
        self.seed = seed

    def _get_inference_mode(self, adapter_path: Optional[str]) -> str:
        """判断实际推理模式。"""
        if self.mode == "vllm":
            if not self.vllm_url:
                return "BLOCKED"  # 缺少 vLLM URL，标 BLOCKED 而非伪造 PASS
            return "vllm"
        return "mock"

    def evaluate(
        self,
        adapter_path: Optional[str] = None,
        baseline_metrics: Optional[MetricsResult] = None,
        baseline_lora_version_id: Optional[int] = None,
    ) -> EvaluationReport:
        """执行 Holdout 评测并返回报告。

        E1: 批推理；E2: 3 指标；E3: 可复现；E4: baseline 对比。
        """
        # 加载 holdout 数据
        try:
            path = locate_holdout(self.dim, self.holdout_root)
        except FileNotFoundError as e:
            logger.error("Holdout 文件缺失: %s", e)
            raise

        cases = load_holdout_cases(path)
        logger.info("[%s] 加载 holdout：%d 条", self.dim, len(cases))

        inf_mode = self._get_inference_mode(adapter_path)

        if inf_mode == "BLOCKED":
            logger.warning(
                "[%s] vLLM 推理 BLOCKED（缺 vllm_url 或 GPU）；"
                "按 no-mock-policy 标 BLOCKED，不出 PASS",
                self.dim,
            )
            return EvaluationReport(
                dim=self.dim,
                lora_version_id=self.lora_version_id,
                metrics=MetricsResult(recall=0.0, precision=0.0, f1=0.0, n_cases=0),
                baseline_metrics=baseline_metrics,
                baseline_lora_version_id=baseline_lora_version_id,
                blocked=True,
                block_reason="vLLM 推理 BLOCKED：缺 vllm_url 或 GPU（no-mock-policy）",
                is_first_run=(baseline_metrics is None),
                inference_mode="BLOCKED",
                holdout_path=str(path),
                n_cases=len(cases),
            )

        # 推理
        infer_results = run_inference(
            cases,
            adapter_path=adapter_path,
            vllm_url=self.vllm_url,
            mode=inf_mode,
            seed=self.seed,
        )
        metrics = compute_metrics(infer_results)
        logger.info(
            "[%s] 评测完成 recall=%.4f precision=%.4f f1=%.4f",
            self.dim,
            metrics.recall,
            metrics.precision,
            metrics.f1,
        )

        # 对比 baseline（E4）
        is_first_run = baseline_metrics is None
        blocked = False
        block_reason = None

        if not is_first_run:
            blocked, block_reason = _check_regression(
                current=metrics,
                baseline=baseline_metrics,  # type: ignore[arg-type]
                threshold=self.REGRESSION_THRESHOLD,
            )
        else:
            logger.info("[%s] 首次评测（无 baseline）→ is_first_run=True，Pass", self.dim)

        return EvaluationReport(
            dim=self.dim,
            lora_version_id=self.lora_version_id,
            metrics=metrics,
            baseline_metrics=baseline_metrics,
            baseline_lora_version_id=baseline_lora_version_id,
            blocked=blocked,
            block_reason=block_reason,
            is_first_run=is_first_run,
            inference_mode=inf_mode,
            holdout_path=str(path),
            n_cases=len(cases),
        )


def _check_regression(
    current: MetricsResult, baseline: MetricsResult, threshold: float = 0.05
) -> tuple[bool, Optional[str]]:
    """判断是否发生退化（任一指标退化 > threshold 触发 Block）。

    [Ref: step_05 §3.5.3 C1]
    """
    checks = [
        ("recall", current.recall, baseline.recall),
        ("precision", current.precision, baseline.precision),
        ("f1", current.f1, baseline.f1),
    ]
    reasons = []
    for name, new, old in checks:
        if old > 0:
            delta = (new - old) / old
        else:
            delta = 0.0 if new >= old else -1.0
        if delta < -threshold:
            reasons.append(
                f"{name} 退化 {delta*100:.1f}%（{old:.4f}→{new:.4f}，阈值 -{threshold*100:.0f}%）"
            )

    if reasons:
        return True, "回归退化触发 Block：" + "；".join(reasons)
    return False, None
