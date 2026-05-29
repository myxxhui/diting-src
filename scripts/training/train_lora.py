"""端到端 LoRA 训练 CLI。

流程：
1. 数据准备：Verified JSONL → alpaca + 切分
2. GPU 检查（必要时降级 dry_run）
3. llamafactory-cli train
4. 发布 training_completed 事件

用法：
  python -m scripts.training.train_lora \
    --lora-name sanity_lora_v0 \
    --task financial_fraud \
    --data training/data/distilled/financial_fraud/<batch>.jsonl \
    --base-model models/Qwen2.5-1.5B-Instruct \
    --rank 16 --epochs 1 --max-steps 50 --no-require-verified

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_04_C3_LLaMA_Factory训练流水线.md]
"""

from __future__ import annotations

import argparse
import logging
import sys

try:
    from apps.super_evo.events.training_complete import (
        TrainingCompletedEvent,
        TrainingEventPublisher,
    )
    _HAS_EVENT_PUBLISHER = True
except ImportError:
    _HAS_EVENT_PUBLISHER = False
    TrainingCompletedEvent = None  # type: ignore
    TrainingEventPublisher = None  # type: ignore
from apps.super_evo.training.data_prep import split_verified_jsonl
from apps.super_evo.training.gpu_check import check_gpu, is_llamafactory_installed
from apps.super_evo.training.trainer import TrainRequest, run_training

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--lora-name", required=True)
    p.add_argument("--task", required=True, help="财务测谎=financial_fraud 等")
    p.add_argument("--data", required=True, help="Verified（或 dry_run）JSONL 文件路径")
    p.add_argument("--base-model", default="models/Qwen2.5-7B-Instruct")
    p.add_argument("--rank", type=int, default=16, choices=[8, 16, 32])
    p.add_argument("--lora-alpha", type=int, default=None)
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--learning-rate", type=float, default=2.0e-4)
    p.add_argument("--max-steps", type=int, default=None, help="sanity 训练快速结束")
    p.add_argument("--no-require-verified", action="store_true", help="允许直接吃蒸馏 JSONL")
    p.add_argument("--dry-run", action="store_true", help="跳过 llamafactory-cli，只校验流水线")
    p.add_argument("--min-free-mib", type=int, default=18000)
    args = p.parse_args()

    split = split_verified_jsonl(
        input_path=args.data,
        output_dir="training/data/llama_factory",
        task_type=args.task,
        require_verified=not args.no_require_verified,
    )
    logger.info(
        "data split: train=%d val=%d test=%d skipped=%d",
        split.n_train,
        split.n_val,
        split.n_test,
        split.skipped,
    )

    gpu = check_gpu(min_free_mib=args.min_free_mib)
    logger.info("gpu: available=%s count=%d reason=%s", gpu.available, gpu.count, gpu.reason)

    dry_run = args.dry_run
    if not is_llamafactory_installed() and not dry_run:
        logger.warning("llamafactory-cli 不在 PATH，自动切换 --dry-run")
        dry_run = True
    if not gpu.available and not dry_run:
        logger.warning("GPU 不可用（%s），自动切换 --dry-run", gpu.reason)
        dry_run = True

    req = TrainRequest(
        lora_name=args.lora_name,
        task=args.task,
        base_model=args.base_model,
        rank=args.rank,
        lora_alpha=args.lora_alpha,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        max_steps=args.max_steps,
    )
    result = run_training(req, dry_run=dry_run)

    if result.return_code != 0:
        logger.error("training failed rc=%d, tail=\n%s", result.return_code, result.stdout_tail)
        return result.return_code

    logger.info(
        "training ok: adapter=%s loss=%s eval=%s",
        result.adapter_path,
        result.final_train_loss,
        result.final_eval_loss,
    )

    if not _HAS_EVENT_PUBLISHER:
        logger.warning("TrainingEventPublisher 不可用（缺少 redis/pydantic），跳过事件发布")
        return 0

    try:
        publisher = TrainingEventPublisher()
        event = TrainingCompletedEvent(
            lora_name=req.lora_name,
            lora_version="v0-sanity" if dry_run else "v1",
            base_model=req.base_model,
            rank=req.rank,
            dataset_path=str(args.data),
            metrics={
                "final_train_loss": result.final_train_loss,
                "final_eval_loss": result.final_eval_loss,
                "n_train": split.n_train,
            },
            output_path=str(result.output_dir),
            config_path=str(result.config_path),
        )
        msg_id = publisher.publish(event)
        logger.info("published training_completed event id=%s msg=%s", event.event_id, msg_id)
    except Exception as exc:
        logger.warning("publish event failed (non-fatal): %s", exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())
