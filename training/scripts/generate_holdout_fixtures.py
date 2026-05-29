"""生成 H001–H050 Holdout JSON 与 manifest（可重复执行覆盖）。

环境变量 CRYO_HOLDOUT_DIR 可覆盖输出目录（测试用）。

工作目录：diting-src 根。运行：python training/scripts/generate_holdout_fixtures.py

[Ref: 03_/01_维度一_极寒防御/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _holdout_root() -> Path:
    env = os.environ.get("CRYO_HOLDOUT_DIR")
    if env:
        return Path(env)
    return _REPO / "training" / "data" / "holdout"


def _case(
    seq: int,
    symbol: str,
    company_name: str,
    fraud_type: str,
    target_engine: str,
    decision: str,
    score: float,
) -> dict:
    return {
        "case_id": f"H{seq:03d}",
        "symbol": symbol,
        "company_name": company_name,
        "fraud_type": fraud_type,
        "target_engine": target_engine,
        "fraud_start_year": 2018 + (seq % 5),
        "exposure_date": f"202{seq % 10}-{(seq % 9) + 1:02d}-15",
        "ground_truth_decision": decision,
        "ground_truth_score": score,
        "evidence": [f"样例证据-{seq}-{target_engine}"],
        "notes": "synthetic fixture",
    }


def main() -> Path:
    from apps.cryo_guard.holdout.schema import HoldoutCaseFile  # noqa: PLC0415

    holdout = _holdout_root()
    holdout.mkdir(parents=True, exist_ok=True)
    seq = 1
    # 30 financial_fraud
    for i in range(30):
        mod = i % 3
        decision = ("reject", "pass", "degrade")[mod]
        score = (0.85, 0.35, 0.55)[mod]
        obj = _case(
            seq,
            f"{600100 + i:06d}",
            f"测试公司财务{i}",
            ("收入确认", "应收异常", "在建工程")[i % 3],
            "financial_fraud",
            decision,
            score,
        )
        HoldoutCaseFile.model_validate(obj)
        (holdout / f"H{seq:03d}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        seq += 1
    for i in range(10):
        mod = i % 3
        decision = ("reject", "pass", "degrade")[mod]
        score = (0.82, 0.38, 0.58)[mod]
        obj = _case(
            seq,
            f"{601100 + i:06d}",
            f"测试公司股东{i}",
            ("违规减持", "质押风险", "资金占用")[i % 3],
            "shareholder_integrity",
            decision,
            score,
        )
        HoldoutCaseFile.model_validate(obj)
        (holdout / f"H{seq:03d}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        seq += 1
    for i in range(10):
        mod = i % 3
        decision = ("reject", "pass", "degrade")[mod]
        score = (0.88, 0.32, 0.52)[mod]
        obj = _case(
            seq,
            f"{603100 + i:06d}",
            f"测试公司关联{i}",
            ("购销异常", "定价不公", "担保链")[i % 3],
            "related_party",
            decision,
            score,
        )
        HoldoutCaseFile.model_validate(obj)
        (holdout / f"H{seq:03d}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        seq += 1
    return holdout


if __name__ == "__main__":
    main()
    print("done: training/data/holdout/H001.json … H050.json")
