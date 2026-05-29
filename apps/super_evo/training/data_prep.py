"""Verified JSONL → LLaMA-Factory alpaca 格式 + 80/10/10 切分。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_04_C3_LLaMA_Factory训练流水线.md]
[Ref: 03_/05_维度五/04_模型训练与部署.md#3.1]
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class DataSplitResult:
    train_path: Path
    val_path: Path
    test_path: Path
    n_train: int
    n_val: int
    n_test: int
    n_total: int
    skipped: int


def _iter_jsonl(p: Path) -> Iterable[dict]:
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _to_alpaca(item: dict) -> dict | None:
    """转 alpaca 三字段；output 保持为 JSON 字符串。

    instruction 允许为空（prompt 全在 input 时），只要 out 非空即有效。
    """
    instruction = item.get("instruction") or ""
    inp = item.get("input") or ""
    out = item.get("output") or ""
    if not out:
        return None
    return {"instruction": instruction, "input": inp, "output": out}


def split_verified_jsonl(
    input_path: str | Path,
    output_dir: str | Path,
    task_type: str,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    require_verified: bool = True,
    seed: int = 42,
) -> DataSplitResult:
    """主入口。

    - require_verified=True 时只接受 metadata.verified=True 的样本（生产）
    - sanity 模式可置 False 直接吃 dry_run JSONL
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    items: list[dict] = []
    skipped = 0
    for raw in _iter_jsonl(input_path):
        meta = raw.get("metadata") or {}
        if require_verified and not meta.get("verified"):
            skipped += 1
            continue
        rec = _to_alpaca(raw)
        if rec is None:
            skipped += 1
            continue
        items.append(rec)

    if not items:
        raise ValueError(f"no eligible records in {input_path} (verified={require_verified})")

    rng = random.Random(seed)
    rng.shuffle(items)

    n_total = len(items)
    n_test = max(1, int(n_total * test_ratio))
    n_val = max(1, int(n_total * val_ratio))
    n_train = n_total - n_test - n_val
    if n_train < 1:
        raise ValueError(f"split too small: total={n_total}")

    train = items[:n_train]
    val = items[n_train : n_train + n_val]
    test = items[n_train + n_val :]

    train_p = output_dir / f"{task_type}_train.json"
    val_p = output_dir / f"{task_type}_val.json"
    test_p = output_dir / f"{task_type}_test.json"
    for p, d in ((train_p, train), (val_p, val), (test_p, test)):
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    register_dataset_info(output_dir, task_type)

    return DataSplitResult(
        train_path=train_p,
        val_path=val_p,
        test_path=test_p,
        n_train=len(train),
        n_val=len(val),
        n_test=len(test),
        n_total=n_total,
        skipped=skipped,
    )


def register_dataset_info(output_dir: Path, task_type: str) -> Path:
    """生成 / 更新 LLaMA-Factory `dataset_info.json`，让 CLI 能按名读取。"""
    p = output_dir / "dataset_info.json"
    info: dict[str, dict] = {}
    if p.exists():
        info = json.loads(p.read_text(encoding="utf-8") or "{}")

    for split in ("train", "val", "test"):
        info[f"{task_type}_{split}"] = {
            "file_name": f"{task_type}_{split}.json",
            "columns": {"prompt": "instruction", "query": "input", "response": "output"},
        }
    p.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
