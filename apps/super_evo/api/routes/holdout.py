"""Holdout 评测 API。

POST /api/holdout/evaluate/{lora_version_id}  → 触发评测
GET  /api/holdout/{dim}/baseline              → 查询当前 prod baseline 指标
POST /api/holdout/{evaluation_id}/override    → manual_gate（ADR 旁路，仅架构师）

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_05_Holdout评测器与CI_Block.md §7.1-D]
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from apps.super_evo.quality.holdout_evaluator import (
    HoldoutEvaluator,
    MetricsResult,
    load_holdout_cases,
    locate_holdout,
)
from apps.super_evo.quality.regression_gate import (
    apply_regression_gate,
    manual_override_gate,
)

router = APIRouter(prefix="/api/holdout", tags=["holdout"])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class EvaluateRequest(BaseModel):
    dim: str = Field(..., description="评测维度：cryo / thrust / narrative")
    adapter_path: Optional[str] = Field(None, description="LoRA adapter 路径（真实训练产物）")
    mode: str = Field("mock", description="推理模式：mock | vllm；vllm 需 GPU（DECISION_PENDING）")
    vllm_url: Optional[str] = Field(None, description="vLLM HTTP 服务 URL（mode=vllm 时必填）")
    holdout_root: Optional[str] = Field(None, description="Holdout 根目录（默认 training/data/holdout）")
    seed: int = Field(42, description="mock 推理随机种子（保证 E3 可复现）")


class EvaluateResponse(BaseModel):
    evaluation_id: Optional[int]
    lora_version_id: int
    dim: str
    n_cases: int
    recall: float
    precision: float
    f1: float
    blocked: bool
    is_first_run: bool
    block_reason: Optional[str]
    inference_mode: str
    delta_recall: Optional[float]
    delta_precision: Optional[float]
    delta_f1: Optional[float]


class BaselineResponse(BaseModel):
    dim: str
    lora_version_id: Optional[int]
    recall: Optional[float]
    precision: Optional[float]
    f1: Optional[float]
    status: str  # found | not_found


class OverrideRequest(BaseModel):
    decided_by: str = Field(..., description="操作人（架构师 ID）")
    adr_ref: str = Field(..., description="ADR 编号，如 ADR-2026-05-01")


# ---------------------------------------------------------------------------
# 路由实现（同步版本，DB 持久化预留异步接口）
# ---------------------------------------------------------------------------


@router.post("/evaluate/{lora_version_id}", response_model=EvaluateResponse)
def trigger_evaluation(lora_version_id: int, req: EvaluateRequest) -> EvaluateResponse:
    """触发 Holdout 评测。

    - mode=mock：不需要 GPU（tier-1 开发验证）
    - mode=vllm：需要 GPU + vllm_url（DECISION_PENDING，tier-2 真实评测）
    """
    holdout_root = Path(req.holdout_root) if req.holdout_root else None

    evaluator = HoldoutEvaluator(
        dim=req.dim,
        lora_version_id=lora_version_id,
        holdout_root=holdout_root,
        vllm_url=req.vllm_url,
        mode=req.mode,
        seed=req.seed,
    )

    try:
        report = evaluator.evaluate(adapter_path=req.adapter_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # 查询 baseline（简化版：从 mock prod 读取；真实版需接 DB）
    baseline = _get_prod_baseline(req.dim)

    gate = apply_regression_gate(
        current_recall=report.metrics.recall,
        current_precision=report.metrics.precision,
        current_f1=report.metrics.f1,
        baseline_recall=baseline.recall if baseline else None,
        baseline_precision=baseline.precision if baseline else None,
        baseline_f1=baseline.f1 if baseline else None,
        dim=req.dim,
    )

    logger.info(
        "[holdout.evaluate] lora_version_id=%d dim=%s blocked=%s mode=%s",
        lora_version_id,
        req.dim,
        report.blocked or gate.blocked,
        report.inference_mode,
    )

    return EvaluateResponse(
        evaluation_id=None,  # 持久化留给完整 DB 版本
        lora_version_id=lora_version_id,
        dim=req.dim,
        n_cases=report.n_cases,
        recall=report.metrics.recall,
        precision=report.metrics.precision,
        f1=report.metrics.f1,
        blocked=report.blocked or gate.blocked,
        is_first_run=report.is_first_run,
        block_reason=report.block_reason or gate.block_reason,
        inference_mode=report.inference_mode,
        delta_recall=gate.delta_recall,
        delta_precision=gate.delta_precision,
        delta_f1=gate.delta_f1,
    )


@router.get("/{dim}/baseline", response_model=BaselineResponse)
def get_baseline(dim: str) -> BaselineResponse:
    """返回指定维度当前 prod baseline 指标（最新 status=prod 版本）。

    E4: baseline 来自真实 lora_versions，禁止伪造（N2）。
    """
    baseline = _get_prod_baseline(dim)
    if baseline is None:
        return BaselineResponse(
            dim=dim, lora_version_id=None, recall=None, precision=None, f1=None, status="not_found"
        )
    return BaselineResponse(
        dim=dim,
        lora_version_id=baseline.lora_version_id,
        recall=baseline.recall,
        precision=baseline.precision,
        f1=baseline.f1,
        status="found",
    )


@router.post("/{evaluation_id}/override")
def override_gate(evaluation_id: int, req: OverrideRequest) -> dict:
    """manual_gate 旁路（仅架构师 ADR 后可执行，C3）。

    严禁 bypass CI 直接发布；override 须携带 ADR 编号。
    """
    try:
        return manual_override_gate(
            evaluation_id=evaluation_id,
            decided_by=req.decided_by,
            adr_ref=req.adr_ref,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ---------------------------------------------------------------------------
# 内部辅助：读 prod baseline（简化 mock 实现，真实版接 DB）
# ---------------------------------------------------------------------------


class _BaselineInfo:
    def __init__(self, lora_version_id: int, recall: float, precision: float, f1: float):
        self.lora_version_id = lora_version_id
        self.recall = recall
        self.precision = precision
        self.f1 = f1


def _get_prod_baseline(dim: str) -> Optional[_BaselineInfo]:
    """从 lora_versions 读 prod baseline（当前为无状态 mock；真实版接 SQLAlchemy DB）。

    N2: baseline 必须来自真实 lora_versions，禁止伪造。
    """
    # TODO: 真实实现需 DB session 查询 lora_versions WHERE status='prod' AND task_type=dim ORDER BY id DESC LIMIT 1
    # 当前返回 None（首次运行 → is_first_run=True，Pass）
    return None
