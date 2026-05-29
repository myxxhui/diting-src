"""LLaMA-Factory 训练器封装。

职责：
- 渲染训练 YAML（替换 ${LORA_NAME} / ${TASK} 等占位）
- 调 llamafactory-cli train
- 抓取关键 metrics（loss、eval_loss）
- 返回 LoRA 输出路径

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_04_C3_LLaMA_Factory训练流水线.md]
[Ref: 03_/05_维度五/04_模型训练与部署.md#4.1]
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TrainRequest:
    lora_name: str
    task: str
    base_model: str = "models/Qwen2.5-7B-Instruct"
    rank: int = 16
    lora_alpha: int | None = None
    epochs: int = 3
    learning_rate: float = 2.0e-4
    max_steps: int | None = None
    dataset_dir: str = "training/data/llama_factory"
    output_root: str = "output"
    fp16: bool = True
    template: str = "qwen"
    extra_overrides: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrainResult:
    lora_name: str
    output_dir: Path
    adapter_path: Path | None
    final_train_loss: float | None
    final_eval_loss: float | None
    metrics_path: Path | None
    stdout_tail: str
    return_code: int
    config_path: Path


def render_config(req: TrainRequest, template_path: str | Path | None = None) -> Path:
    template_path = Path(
        template_path or Path(__file__).parent / "configs" / "_template_lora.yaml"
    )
    text = template_path.read_text(encoding="utf-8")

    alpha = req.lora_alpha or req.rank * 2
    output_dir = Path(req.output_root) / req.lora_name
    output_dir.mkdir(parents=True, exist_ok=True)

    text = text.replace("${LORA_NAME}", req.lora_name)
    text = text.replace("${TASK}", req.task)
    text = re.sub(r"model_name_or_path:.*", f"model_name_or_path: {req.base_model}", text)
    text = re.sub(r"^template:.*", f"template: {req.template}", text, flags=re.MULTILINE)
    text = re.sub(r"^lora_rank:.*", f"lora_rank: {req.rank}", text, flags=re.MULTILINE)
    text = re.sub(r"^lora_alpha:.*", f"lora_alpha: {alpha}", text, flags=re.MULTILINE)
    text = re.sub(r"^num_train_epochs:.*", f"num_train_epochs: {req.epochs}", text, flags=re.MULTILINE)
    text = re.sub(r"^learning_rate:.*", f"learning_rate: {req.learning_rate}", text, flags=re.MULTILINE)
    text = re.sub(r"^dataset_dir:.*", f"dataset_dir: {req.dataset_dir}", text, flags=re.MULTILINE)
    text = re.sub(r"^fp16:.*", f"fp16: {'true' if req.fp16 else 'false'}", text, flags=re.MULTILINE)

    if req.max_steps:
        text = text.rstrip() + f"\nmax_steps: {req.max_steps}\n"

    for k, v in req.extra_overrides.items():
        val = json.dumps(v) if not isinstance(v, str) else v
        text = re.sub(rf"^{re.escape(k)}:.*", f"{k}: {val}", text, flags=re.MULTILINE)

    cfg_path = output_dir / "train_config.yaml"
    cfg_path.write_text(text, encoding="utf-8")
    return cfg_path


def _parse_loss_from_log(tail: str) -> tuple[float | None, float | None]:
    """从 LLaMA-Factory 日志末尾抽取 train loss / eval loss。"""
    train, eval_ = None, None
    for m in re.finditer(r"'loss': (\d+\.\d+)", tail):
        train = float(m.group(1))
    for m in re.finditer(r"'eval_loss': (\d+\.\d+)", tail):
        eval_ = float(m.group(1))
    return train, eval_


def run_training(req: TrainRequest, dry_run: bool = False) -> TrainResult:
    cfg_path = render_config(req)
    output_dir = Path(req.output_root) / req.lora_name

    cmd = ["llamafactory-cli", "train", str(cfg_path)]
    logger.info("running: %s", " ".join(cmd))

    if dry_run:
        adapter_dir = output_dir
        adapter_dir.mkdir(parents=True, exist_ok=True)
        (adapter_dir / "adapter_config.json").write_text(
            json.dumps(
                {
                    "peft_type": "LORA",
                    "r": req.rank,
                    "lora_alpha": req.lora_alpha or req.rank * 2,
                }
            ),
            encoding="utf-8",
        )
        (adapter_dir / "adapter_model.bin").write_bytes(b"\x00" * 1024)
        metrics = {"final_train_loss": 0.42, "final_eval_loss": 0.55, "dry_run": True}
        (adapter_dir / "all_results.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        return TrainResult(
            lora_name=req.lora_name,
            output_dir=adapter_dir,
            adapter_path=adapter_dir / "adapter_model.bin",
            final_train_loss=metrics["final_train_loss"],
            final_eval_loss=metrics["final_eval_loss"],
            metrics_path=adapter_dir / "all_results.json",
            stdout_tail="[dry_run] llamafactory-cli not invoked",
            return_code=0,
            config_path=cfg_path,
        )

    env = os.environ.copy()
    env.setdefault("WANDB_PROJECT", "diting-super-evo")
    # 不 capture_output，让 llamafactory 输出直接流向 pod stdout（便于调试）
    import tempfile, io
    log_file = output_dir / "llamafactory_stdout.log"
    with open(log_file, "w", encoding="utf-8") as lf:
        proc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env)
    try:
        stdout = log_file.read_text(encoding="utf-8")
    except Exception:
        stdout = ""
    tail = "\n".join(stdout.strip().splitlines()[-200:])
    logger.info("=== llamafactory stdout (last 50 lines) ===\n%s", "\n".join(stdout.strip().splitlines()[-50:]))

    metrics_path = output_dir / "all_results.json"
    final_train, final_eval = _parse_loss_from_log(tail)
    if metrics_path.exists():
        try:
            data = json.loads(metrics_path.read_text(encoding="utf-8"))
            final_train = data.get("train_loss") or final_train
            final_eval = data.get("eval_loss") or final_eval
        except Exception:
            pass

    adapter_candidate = output_dir / "adapter_model.bin"
    adapter_safetensors = output_dir / "adapter_model.safetensors"
    adapter_path = (
        adapter_candidate
        if adapter_candidate.exists()
        else (adapter_safetensors if adapter_safetensors.exists() else None)
    )

    return TrainResult(
        lora_name=req.lora_name,
        output_dir=output_dir,
        adapter_path=adapter_path,
        final_train_loss=final_train,
        final_eval_loss=final_eval,
        metrics_path=metrics_path if metrics_path.exists() else None,
        stdout_tail=tail,
        return_code=proc.returncode,
        config_path=cfg_path,
    )
