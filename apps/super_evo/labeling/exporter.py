"""Label Studio 标注导出为 Verified JSONL。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_03_C2_Label_Studio部署.md]
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.super_evo.labeling.client import LabelStudioClient


def _extract_label_payload(annotation: dict[str, Any], _task_type: str) -> dict[str, Any]:
    """从 Label Studio annotation 中抽取与 task_type 对应的标签。"""
    result: dict[str, Any] = {}
    for r in annotation.get("result", []):
        name = r.get("from_name")
        value = r.get("value", {})
        if name == "decision" and "choices" in value:
            result["decision"] = value["choices"][0] if value["choices"] else None
        elif name == "risk_score" and "rating" in value:
            result["risk_score"] = float(value["rating"]) / 10.0
        elif name == "evidence" and "text" in value:
            result["evidence"] = [s.strip() for s in value["text"] if s.strip()]
        elif name == "notes" and "text" in value:
            result["notes"] = " ".join(value["text"])
        elif name == "five_required" and "choices" in value:
            result["five_required"] = value["choices"]
        elif name == "completeness" and "rating" in value:
            result["completeness"] = int(value["rating"])
        elif name == "nli_label" and "choices" in value:
            result["nli_label"] = value["choices"][0] if value["choices"] else None
    return result


def export_to_verified_jsonl(
    client: LabelStudioClient,
    project_id: int,
    task_type: str,
    output_path: str | Path,
    require_min_annotators: int = 1,
) -> int:
    """从 Label Studio 拉取已审任务并写 Verified JSONL。"""
    items = client.export_annotations(project_id, fmt="JSON")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    n_written = 0
    with output_path.open("w", encoding="utf-8") as f:
        for it in items:
            anns = it.get("annotations") or []
            if len(anns) < require_min_annotators:
                continue
            label = _extract_label_payload(anns[0], task_type)
            if not label.get("decision") and task_type in {"financial_fraud", "shareholder", "related_party"}:
                continue
            if task_type == "nli" and not label.get("nli_label"):
                continue
            if task_type == "thesis" and not label.get("five_required") and label.get("completeness") is None:
                continue

            data = it.get("data") or {}
            verifier = (anns[0].get("completed_by") or {}).get("email", "ls-user")

            inner_output: dict[str, Any] = {}
            if "decision" in label:
                inner_output["decision"] = label["decision"]
            if "risk_score" in label:
                inner_output["risk_score"] = label["risk_score"]
            inner_output.setdefault("evidence", label.get("evidence", []))
            if label.get("notes"):
                inner_output["reasoning"] = label["notes"]
            inner_output.setdefault("confidence", 1.0)
            for k in ("five_required", "completeness", "nli_label"):
                if k in label:
                    inner_output[k] = label[k]

            record = {
                "instruction": data.get("_instruction", ""),
                "input": data.get("input", ""),
                "output": json.dumps(inner_output, ensure_ascii=False),
                "metadata": {
                    "task_type": task_type,
                    "teacher_model": "verified",
                    "distill_timestamp": (it.get("created_at") or ""),
                    "verified": True,
                    "verifier": verifier,
                    "sample_id": data.get("_sample_id"),
                    "batch_id": data.get("_batch_id"),
                    "verified_at": datetime.utcnow().isoformat() + "Z",
                },
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            n_written += 1
    return n_written
