"""回归门（Regression Gate）— 读 YAML 阈值，与 holdout_evaluator 配合触发 CI Block。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_05_Holdout评测器与CI_Block.md §3.5.3 C1-C4]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 阈值配置（YAML 驱动，可在 CI ConfigMap 覆盖）
# ---------------------------------------------------------------------------

_DEFAULT_THRESHOLD_YAML = Path(__file__).parent / "regression_thresholds.yaml"


def load_thresholds(path: Path | None = None) -> dict:
    """加载退化阈值 yaml；缺失时返回内置默认值。"""
    target = path or _DEFAULT_THRESHOLD_YAML
    if not target.exists():
        return {"default": {"recall": 0.05, "precision": 0.05, "f1": 0.05}}

    import yaml  # optional dep，仅 quality 模块需要
    with target.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Gate 结果
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    blocked: bool
    block_reason: Optional[str]
    delta_recall: Optional[float]
    delta_precision: Optional[float]
    delta_f1: Optional[float]


def apply_regression_gate(
    current_recall: float,
    current_precision: float,
    current_f1: float,
    baseline_recall: Optional[float],
    baseline_precision: Optional[float],
    baseline_f1: Optional[float],
    dim: str = "default",
    threshold_path: Path | None = None,
) -> GateResult:
    """评估当前版本与 baseline 的退化情况。

    首次运行（baseline 为 None）→ Pass（is_first_run）。
    任一指标退化 > 阈值 → blocked=True。

    [Ref: step_05 §3.5.3 C1]
    """
    if baseline_recall is None:
        logger.info("[%s] 无 baseline，首次运行 → Pass", dim)
        return GateResult(
            blocked=False,
            block_reason=None,
            delta_recall=None,
            delta_precision=None,
            delta_f1=None,
        )

    thresholds = load_thresholds(threshold_path)
    dim_thresholds = thresholds.get(dim, thresholds.get("default", {}))

    def _delta(new: float, old: float) -> float:
        return (new - old) / old if old > 0 else (0.0 if new >= old else -1.0)

    delta_recall = _delta(current_recall, baseline_recall)
    delta_precision = _delta(current_precision, baseline_precision or 0.0)
    delta_f1 = _delta(current_f1, baseline_f1 or 0.0)

    reasons = []
    for metric, delta, threshold_key in [
        ("recall", delta_recall, "recall"),
        ("precision", delta_precision, "precision"),
        ("f1", delta_f1, "f1"),
    ]:
        thr = dim_thresholds.get(threshold_key, 0.05)
        if delta < -thr:
            reasons.append(
                f"{metric} 退化 {delta*100:.1f}%（阈值 -{thr*100:.0f}%）"
            )

    if reasons:
        return GateResult(
            blocked=True,
            block_reason="CI Block：" + "；".join(reasons),
            delta_recall=delta_recall,
            delta_precision=delta_precision,
            delta_f1=delta_f1,
        )

    return GateResult(
        blocked=False,
        block_reason=None,
        delta_recall=delta_recall,
        delta_precision=delta_precision,
        delta_f1=delta_f1,
    )


# ---------------------------------------------------------------------------
# 手动旁路（manual_gate）— 仅架构师 ADR 后可 override（C3）
# ---------------------------------------------------------------------------


def manual_override_gate(
    evaluation_id: int,
    decided_by: str,
    adr_ref: str,
) -> dict:
    """生成 manual_gate override 记录（不自动写库；由 API 层写入）。

    [Ref: step_05 §3.5.3 C3 - 仅架构师 ADR 后可旁路]
    """
    if not adr_ref.startswith("ADR-"):
        raise ValueError(f"manual_gate 须携带有效 ADR 编号（如 ADR-2026-05-01），got: {adr_ref!r}")
    return {
        "evaluation_id": evaluation_id,
        "blocked": False,
        "decided_by": decided_by,
        "manual_gate_adr": adr_ref,
        "override": True,
    }
