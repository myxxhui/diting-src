#!/usr/bin/env python3
"""D5 step_03 · 蒸馏 export → Label Studio + labelings 审计.

默认读 cryo Teacher 真蒸馏 export（training/data/llama_factory/*_train.json）。
凭证缺失或文件为空时 fail fast，不用 sanity_dry_run 占位。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_03 §7.2]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from apps.super_evo.db.database import get_session
from apps.super_evo.db.models import LabelingRecord
from apps.super_evo.labeling.client import LabelStudioClient, load_template
from apps.super_evo.labeling.importer import PROJECT_TITLE_BY_TASK, import_jsonl, jsonl_to_tasks

_LF = Path("training/data/llama_factory")

DIM_MAP = {
    "cryo": ("financial_fraud", _LF / "financial_fraud_train.json"),
    "thrust": ("shareholder", _LF / "shareholder_train.json"),
    "narrative": ("related_party", _LF / "related_party_train.json"),
}


def _resolve_jsonl(dim: str, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    _, default = DIM_MAP[dim]
    return default


def _ensure_project(client: LabelStudioClient, task_type: str) -> int:
    title = PROJECT_TITLE_BY_TASK[task_type]
    xml = load_template(task_type)
    proj = client.create_project(title, xml, description=f"Diting {task_type}")
    return int(proj["id"])


def _persist_labelings(batch_date: str, dimension: str, task_type: str, jsonl_path: Path, project_id: int | None) -> int:
    tasks = jsonl_to_tasks(jsonl_path, task_type)
    session = get_session()
    n = 0
    try:
        for t in tasks:
            data = t.get("data") or {}
            sid = str(data.get("_sample_id") or f"{dimension}-{n}")
            rec = (
                session.query(LabelingRecord)
                .filter_by(batch_date=batch_date, dimension=dimension, sample_id=sid)
                .one_or_none()
            )
            if rec is None:
                rec = LabelingRecord(
                    batch_date=batch_date,
                    dimension=dimension,
                    sample_id=sid,
                    task_type=task_type,
                    ls_project_id=project_id,
                    status="imported",
                    payload_json=json.dumps(data, ensure_ascii=False),
                )
                session.add(rec)
            else:
                rec.ls_project_id = project_id
                rec.status = "imported"
            n += 1
        session.commit()
    finally:
        session.close()
    return n


def run_import(dimension: str, jsonl_path: str | None, batch_date: str | None, skip_ls: bool) -> dict:
    if dimension not in DIM_MAP:
        raise ValueError(f"未知 dimension: {dimension}")
    task_type, _ = DIM_MAP[dimension]
    path = _resolve_jsonl(dimension, jsonl_path)
    if not path.exists():
        return {
            "dimension": dimension,
            "success": False,
            "error": f"蒸馏 export 不存在: {path}；请先 make cryo-step03-export",
        }
    tasks = jsonl_to_tasks(path, task_type)
    if not tasks:
        return {
            "dimension": dimension,
            "success": False,
            "error": f"蒸馏 export 为空: {path}；请先 make cryo-step03-distill + export",
        }
    bd = batch_date or datetime.now(timezone.utc).strftime("%Y%m%d")
    project_id: int | None = None
    imported = 0
    ls_ok = False
    if not skip_ls:
        client = LabelStudioClient()
        health = client.health()
        if health.get("ok"):
            project_id = _ensure_project(client, task_type)
            imported = import_jsonl(client, project_id, path, task_type)
            ls_ok = True
            client.close()
    db_n = _persist_labelings(bd, dimension, task_type, path, project_id)
    return {
        "dimension": dimension,
        "task_type": task_type,
        "batch_date": bd,
        "jsonl": str(path),
        "ls_imported": imported,
        "labelings_rows": db_n,
        "ls_ok": ls_ok,
        "success": db_n > 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dimension", choices=["cryo", "thrust", "narrative"])
    parser.add_argument("--jsonl", default=None, help="显式指定 export 路径（默认 llama_factory *_train.json）")
    parser.add_argument("--date", dest="batch_date", default=None)
    parser.add_argument("--skip-ls", action="store_true", help="仅写 labelings 表，不连 LS")
    args = parser.parse_args()
    report = run_import(args.dimension, args.jsonl, args.batch_date, args.skip_ls)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report.get("success"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
