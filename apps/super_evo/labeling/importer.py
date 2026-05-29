"""蒸馏 JSONL → Label Studio 任务导入器。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_03_C2_Label_Studio部署.md]
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.super_evo.labeling.client import LabelStudioClient

PROJECT_TITLE_BY_TASK = {
    "financial_fraud": "Diting · 财务测谎 · Verified",
    "shareholder": "Diting · 大股东诚信 · Verified",
    "related_party": "Diting · 关联交易 · Verified",
    "thesis": "Diting · Thesis 卡片 · Review",
    "nli": "Diting · 叙事一致性 NLI · Verified",
}


def _as_teacher_output(item: dict[str, Any]) -> str:
    out = item.get("output")
    if isinstance(out, str):
        return out
    if out is None:
        return ""
    return json.dumps(out, ensure_ascii=False)


def jsonl_to_tasks(jsonl_path: str | Path, task_type: str) -> list[dict[str, Any]]:
    """读取蒸馏 JSONL 或 LLaMA-Factory JSON 数组，转 Label Studio 任务格式."""
    return _items_to_tasks(_load_distill_items(jsonl_path), jsonl_path, task_type)


def _load_distill_items(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if p.suffix == ".jsonl":
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    data = json.loads(raw)
    if isinstance(data, list):
        return data
    raise ValueError(f"不支持的蒸馏文件格式: {p}")


def _items_to_tasks(items: list[dict[str, Any]], path: Path, task_type: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        meta = item.get("metadata") or {}
        data: dict[str, Any] = {
            "input": item.get("input", ""),
            "teacher_output": _as_teacher_output(item),
            "_sample_id": meta.get("sample_id") or f"{path.stem}#{i}",
            "_task_type": task_type,
            "_batch_id": meta.get("batch_id"),
        }
        if task_type == "nli":
            data["premise"] = item.get("premise") or item.get("input", "")
            data["hypothesis"] = item.get("hypothesis") or meta.get("hypothesis") or ""
        tasks.append({"data": data})
    return tasks


def jsonl_to_tasks_legacy(jsonl_path: str | Path, task_type: str) -> list[dict[str, Any]]:
    """兼容旧名."""
    return jsonl_to_tasks(jsonl_path, task_type)


def import_jsonl(
    client: LabelStudioClient,
    project_id: int,
    jsonl_path: str | Path,
    task_type: str,
) -> int:
    tasks = jsonl_to_tasks(jsonl_path, task_type)
    if not tasks:
        return 0
    client.import_tasks(project_id, tasks)
    return len(tasks)
