"""将 Verified 样本导出为 LLaMA-Factory alpaca JSON + 80/10/10 切分。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_03_Teacher蒸馏.md]
"""
from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path

from sqlalchemy import select

from apps.cryo_guard.db.models import TeacherDistill
from apps.cryo_guard.db.sync_session import session_scope

EXPORT_STEM = {
    "financial_fraud": "financial_fraud",
    "shareholder_integrity": "shareholder",
    "related_party": "related_party",
}


def _out_dir() -> Path:
    return Path(os.environ.get("CRYO_LLAMA_FACTORY_OUT", "training/data/llama_factory"))


def export_engine_to_llama_factory(
    engine: str,
    *,
    out_dir: Path | None = None,
    rng_seed: int = 42,
) -> dict:
    """导出单引擎 verified=true 行为 alpaca 列表 JSON 与 train/val/test。"""
    stem = EXPORT_STEM[engine]
    root = out_dir or _out_dir()
    root.mkdir(parents=True, exist_ok=True)

    with session_scope() as session:
        rows = (
            session.scalars(
                select(TeacherDistill).where(
                    TeacherDistill.engine_name == engine,
                    TeacherDistill.verified.is_(True),
                    TeacherDistill.parse_status == "ok",
                    TeacherDistill.teacher_model != "cryo_mock_teacher",
                )
            )
        ).all()

    data: list[dict] = []
    for r in rows:
        data.append(
            {
                "instruction": r.instruction,
                "input": r.input,
                "output": r.output,
                "metadata": {
                    "symbol": r.symbol,
                    "report_period": r.report_period,
                    "teacher_model": r.teacher_model,
                    "verifier": r.verifier,
                    "verified_at": r.verified_at.isoformat() if r.verified_at else None,
                },
            }
        )

    random.Random(rng_seed).shuffle(data)
    n = len(data)
    if n == 0:
        merged = root / f"{stem}.json"
        merged.write_text("[]", encoding="utf-8")
        for suffix in ("_train", "_val", "_test"):
            (root / f"{stem}{suffix}.json").write_text("[]", encoding="utf-8")
        return {"engine": engine, "stem": stem, "total": 0, "train": 0, "val": 0, "test": 0}

    n_val = max(1, n // 10)
    n_test = max(1, n // 10)
    if n_val + n_test >= n:
        n_val = max(1, n // 3)
        n_test = max(1, n // 3)
    test = data[:n_test]
    val = data[n_test : n_test + n_val]
    train = data[n_test + n_val :]

    (root / f"{stem}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / f"{stem}_train.json").write_text(
        json.dumps(train, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (root / f"{stem}_val.json").write_text(json.dumps(val, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / f"{stem}_test.json").write_text(
        json.dumps(test, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "engine": engine,
        "stem": stem,
        "total": n,
        "train": len(train),
        "val": len(val),
        "test": len(test),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--engine",
        choices=["financial_fraud", "shareholder_integrity", "related_party", "all"],
        default="all",
    )
    args = ap.parse_args()
    targets = list(EXPORT_STEM.keys()) if args.engine == "all" else [args.engine]
    for e in targets:
        print(export_engine_to_llama_factory(e))


if __name__ == "__main__":
    main()
