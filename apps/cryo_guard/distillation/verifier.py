"""Verified：自动接受低风险 +（可选）交互审阅。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_03_Teacher蒸馏.md]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

from sqlalchemy import select

from apps.cryo_guard.db.models import TeacherDistill
from apps.cryo_guard.db.sync_session import session_scope


def auto_accept_if_safe(
    engine: str,
    score_band: tuple[float, float] = (0.05, 0.35),
) -> int:
    """对低风险 pass + 合法 JSON 批量标 verified（阶段 A / 提速用）。"""
    accepted = 0
    with session_scope() as session:
        rows = (
            session.scalars(
                select(TeacherDistill).where(
                    TeacherDistill.engine_name == engine,
                    TeacherDistill.verified.is_(False),
                    TeacherDistill.parse_status == "ok",
                )
            )
        ).all()
        for it in rows:
            try:
                out = json.loads(it.output)
            except json.JSONDecodeError:
                continue
            score = float(out.get("risk_score", 1.0))
            if not (score_band[0] <= score <= score_band[1]):
                continue
            if out.get("decision") != "pass":
                continue
            it.verified = True
            it.verifier = "auto_low_risk"
            it.verifier_decision = "accept"
            it.verified_at = datetime.utcnow()
            accepted += 1
    return accepted


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    args = ap.parse_args()
    n = auto_accept_if_safe(args.engine)
    print(f"自动接受 {n} 条低风险样本")


if __name__ == "__main__":
    main()
