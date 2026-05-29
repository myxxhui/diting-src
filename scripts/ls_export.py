#!/usr/bin/env python3
"""D5 step_03 · Label Studio → Verified JSONL + 进度快照.

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_03 §7.2]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func

from apps.super_evo.db.database import get_session
from apps.super_evo.db.models import LabelingRecord
from apps.super_evo.labeling.client import LabelStudioClient
from apps.super_evo.labeling.exporter import export_to_verified_jsonl
from apps.super_evo.labeling.importer import PROJECT_TITLE_BY_TASK

DIM_TASK = {
    "cryo": "financial_fraud",
    "thrust": "shareholder",
    "narrative": "related_party",
}


def _export_dim(dimension: str, batch_date: str, skip_ls: bool) -> dict:
    task_type = DIM_TASK[dimension]
    out_dir = Path("training/data/verified") / batch_date
    out_path = out_dir / f"{dimension}_{task_type}.jsonl"
    n = 0
    ls_ok = False
    skipped = 0
    if not skip_ls:
        client = LabelStudioClient()
        health = client.health()
        if health.get("ok"):
            title = PROJECT_TITLE_BY_TASK[task_type]
            proj = client.get_project_by_title(title)
            if proj:
                n = export_to_verified_jsonl(client, int(proj["id"]), task_type, out_path)
                ls_ok = True
            client.close()
    if n == 0:
        session = get_session()
        try:
            rows = (
                session.query(LabelingRecord)
                .filter_by(batch_date=batch_date, dimension=dimension)
                .limit(50)
                .all()
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            skipped = 0
            with out_path.open("w", encoding="utf-8") as f:
                for r in rows:
                    try:
                        payload = json.loads(r.payload_json) if r.payload_json else {}
                    except json.JSONDecodeError:
                        print(
                            f"[WARN] payload_json 解析失败，跳过：dim={r.dimension} "
                            f"sample_id={r.sample_id} len={len(r.payload_json or '')}",
                            file=sys.stderr,
                        )
                        skipped += 1
                        continue
                    record = {
                        "instruction": "",
                        "input": payload.get("input", ""),
                        "output": payload.get("teacher_output", "{}"),
                        "metadata": {
                            "task_type": task_type,
                            "verified": False,
                            "sample_id": r.sample_id,
                            "batch_id": batch_date,
                        },
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    n += 1
        finally:
            session.close()
    return {
        "dimension": dimension,
        "exported": n,
        "skipped_bad_json": skipped,
        "path": str(out_path),
        "ls_ok": ls_ok,
        "success": n >= 0,
    }


def _progress() -> dict:
    session = get_session()
    try:
        rows = (
            session.query(LabelingRecord.dimension, LabelingRecord.status, func.count(LabelingRecord.id))
            .group_by(LabelingRecord.dimension, LabelingRecord.status)
            .all()
        )
        table = [{"dimension": d, "status": s, "count": int(c)} for d, s, c in rows]
    finally:
        session.close()
    client = LabelStudioClient()
    ls_projects = []
    if client.health().get("ok"):
        for dim, tt in DIM_TASK.items():
            title = PROJECT_TITLE_BY_TASK[tt]
            p = client.get_project_by_title(title)
            if p:
                ls_projects.append(
                    {"dimension": dim, "project_id": p["id"], "tasks": client.get_task_count(int(p["id"]))}
                )
    client.close()
    return {"labelings": table, "ls_projects": ls_projects, "ok": True}


def _status() -> dict:
    session = get_session()
    try:
        total = session.query(func.count(LabelingRecord.id)).scalar()
        by_dim = (
            session.query(LabelingRecord.dimension, func.count(LabelingRecord.id))
            .group_by(LabelingRecord.dimension)
            .all()
        )
    finally:
        session.close()
    return {
        "labelings_total": int(total or 0),
        "by_dimension": {d: int(c) for d, c in by_dim},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=["export", "export-all", "progress", "status"],
    )
    parser.add_argument("--dimension", choices=["cryo", "thrust", "narrative"], default="cryo")
    parser.add_argument("--date", dest="batch_date", default=None)
    parser.add_argument("--skip-ls", action="store_true")
    args = parser.parse_args()
    bd = args.batch_date or datetime.now(timezone.utc).strftime("%Y%m%d")
    if args.mode == "progress":
        out = _progress()
    elif args.mode == "status":
        out = _status()
    elif args.mode == "export-all":
        parts = [_export_dim(d, bd, args.skip_ls) for d in DIM_TASK]
        out = {"batch_date": bd, "exports": parts, "ok": True}
    else:
        out = _export_dim(args.dimension, bd, args.skip_ls)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if out.get("ok") is False or out.get("success") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
