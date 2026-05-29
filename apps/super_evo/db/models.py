"""Label Studio 导入/导出审计表 + LoRA 训练版本注册表 + Holdout 评测结果表.

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_03_C2_Label_Studio部署.md]
[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_04_C3_LLaMA_Factory训练流水线.md]
[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_05_Holdout评测器与CI_Block.md]
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Index, JSON, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LoraVersion(Base):
    """LoRA 训练版本注册表。

    每次训练完成后写入一行；E4 可重跑幂等：同 lora_name + dataset_dvc_rev 拒重训。

    [Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_04_C3_LLaMA_Factory训练流水线.md §3.5.3 E4]
    """

    __tablename__ = "lora_versions"
    __table_args__ = (
        UniqueConstraint("lora_name", "version", name="uq_lora_name_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lora_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    base_model: Mapped[str] = mapped_column(String(128), nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    dataset_dvc_rev: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=16)
    epochs: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    max_steps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    train_metrics: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    wandb_run_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    minio_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    adapter_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )  # pending | training | completed | failed | dry_run
    is_dry_run: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class HoldoutEvaluation(Base):
    """Holdout 评测结果表。

    每次评测写入一行；blocked=True 触发 CI Block。
    [Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_05_Holdout评测器与CI_Block.md §3]
    """

    __tablename__ = "holdout_evaluations"
    __table_args__ = (
        Index("ix_holdout_lora_dim", "lora_version_id", "dim"),
        Index("ix_holdout_blocked_created", "blocked", "evaluated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lora_version_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    dim: Mapped[str] = mapped_column(String(32), nullable=False)  # cryo / thrust / narrative
    holdout_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    n_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 当前版本指标
    recall: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    precision: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    f1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    metrics_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # baseline 指标（前一 prod 版本）
    baseline_lora_version_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    baseline_recall: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    baseline_precision: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    baseline_f1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    baseline_metrics_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # delta（新 - 旧）/ 旧；负值代表退化
    delta_recall: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delta_precision: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delta_f1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_first_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    block_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # ci / manual_gate
    manual_gate_adr: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # 推理模式
    inference_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="mock"
    )  # mock | vllm | BLOCKED
    wandb_run_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LabelingRecord(Base):
    __tablename__ = "labelings"
    __table_args__ = (UniqueConstraint("batch_date", "dimension", "sample_id", name="uq_labeling_batch_dim_sample"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_date: Mapped[str] = mapped_column(String(8), index=True)
    dimension: Mapped[str] = mapped_column(String(32), index=True)
    sample_id: Mapped[str] = mapped_column(String(128))
    task_type: Mapped[str] = mapped_column(String(64))
    ls_project_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ls_task_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="imported")
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
