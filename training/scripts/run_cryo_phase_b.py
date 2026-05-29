#!/usr/bin/env python3
"""cryo_guard step_03 阶段 B 编排：三引擎蒸馏 → auto_verify → 导出 → holdout_guard。

在 **diting-src 仓库根** 执行（与 `training/scripts/holdout_guard.py` 一致）：

- **本机可做**：SQLite、`cryo_guard.db`、本机或远程 Teacher（Anthropic / 维度五 HTTP）。
- **启动期**：候选池有限（~67 条），需 **ANTHROPIC_API_KEY**；禁止 CRYO_GUARD_DISTILL_MOCK 业务路径。
- **推荐**：笔记本直连 Teacher 时设置 ``CRYO_SKIP_D5=1`` + ``ANTHROPIC_API_KEY``。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_03_Teacher蒸馏.md]
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def _ensure_repo_path() -> None:
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))


def _bootstrap_env() -> None:
    _ensure_repo_path()
    from apps.common.repo_env import load_repo_dotenv

    load_repo_dotenv(_REPO)


def _has_teacher_key() -> bool:
    from apps.cryo_guard.config import settings
    from apps.common.repo_env import anthropic_key_configured

    return anthropic_key_configured() or bool(settings.teacher_api_key)


def preflight() -> int:
    """检查数据源与 Holdout 目录；不调用 Teacher。"""
    _bootstrap_env()
    from sqlalchemy import func, select

    from apps.cryo_guard.config import settings
    from apps.cryo_guard.db.models import Announcement, FinancialReport, RelatedPartyRaw
    from apps.cryo_guard.db.sync_session import session_scope
    from apps.common.no_mock_policy import reject_business_mock

    reject_business_mock("CRYO_GUARD_DISTILL_MOCK", context="cryo phase B preflight")

    holdout_root = Path(os.environ.get("CRYO_HOLDOUT_DIR", _REPO / "training/data/holdout"))
    print(f"[preflight] db_url: {settings.db_url}")
    print(f"[preflight] Holdout 目录: {holdout_root} exists={holdout_root.is_dir()}")
    skip_d5 = os.environ.get("CRYO_SKIP_D5", "").lower() in ("1", "true", "yes")
    has_key = _has_teacher_key()
    print(f"[preflight] CRYO_SKIP_D5={skip_d5} ANTHROPIC_API_KEY={'set' if has_key else 'unset'}")

    try:
        with session_scope() as s:
            n_fr = s.scalar(
                select(func.count()).select_from(FinancialReport).where(FinancialReport.report_type == "annual")
            )
            n_ann = s.scalar(select(func.count()).select_from(Announcement))
            n_rp = s.scalar(select(func.count()).select_from(RelatedPartyRaw))
        print(f"[preflight] 候选池: annual财报={n_fr} 公告={n_ann} 关联交易行={n_rp}")
    except Exception as exc:
        print(f"[preflight] DB 连接失败: {exc}")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="cryo_guard Teacher 蒸馏阶段 B 编排")
    ap.add_argument(
        "--smoke",
        action="store_true",
        help="每引擎最多新增 N 条（默认 5，可用 CRYO_DISTILL_SMOKE_LIMIT 覆盖）",
    )
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--skip-auto-verify", action="store_true", help="不跑 auto_accept_if_safe")
    ap.add_argument("--skip-export", action="store_true")
    ap.add_argument("--skip-guard", action="store_true", help="不跑 training/scripts/holdout_guard.py")
    ap.add_argument(
        "--verify-holdout-manifest",
        action="store_true",
        help="对 Holdout 目录跑 holdout_guard --verify（SHA256）",
    )
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    _bootstrap_env()

    if args.preflight_only:
        return preflight()

    from apps.common.no_mock_policy import reject_business_mock

    reject_business_mock("CRYO_GUARD_DISTILL_MOCK", context="cryo phase B")

    if not _has_teacher_key():
        print(
            "\n❌ 未配置 ANTHROPIC_API_KEY，无法执行真实 Teacher 蒸馏（no-mock-policy）。"
            "\n   请配置密钥后重跑，或仅执行 ``--preflight-only`` / ``make cryo-step03-test``。\n"
        )
        return 2

    _ensure_repo_path()
    from apps.cryo_guard.distillation.distill_runner import TARGETS, run as distill_run
    from apps.cryo_guard.distillation.exporter import export_engine_to_llama_factory
    from apps.cryo_guard.distillation.verifier import auto_accept_if_safe

    if preflight() != 0:
        return 1

    smoke_limit: int | None = None
    if args.smoke:
        smoke_limit = int(os.environ.get("CRYO_DISTILL_SMOKE_LIMIT", "5"))

    print(
        "\n[提示] 真实 Teacher 将产生 API 费用。"
        "笔记本可设 CRYO_SKIP_D5=1 直连 Anthropic。\n"
    )

    for eng, target in TARGETS.items():
        n = distill_run(eng, target, limit=smoke_limit, dry_run=False)
        logging.info("engine=%s new_rows=%s", eng, n)
        if not args.skip_auto_verify and n > 0:
            accepted = auto_accept_if_safe(eng)
            logging.info("engine=%s auto_accept=%s", eng, accepted)

    if not args.skip_export:
        for eng in TARGETS:
            stats = export_engine_to_llama_factory(eng)
            logging.info("export %s", stats)

    lf = Path(os.environ.get("CRYO_LLAMA_FACTORY_OUT", _REPO / "training/data/llama_factory"))
    training_files = [
        lf / "financial_fraud.json",
        lf / "shareholder.json",
        lf / "related_party.json",
    ]
    existing = [f for f in training_files if f.is_file() and f.stat().st_size > 2]

    if args.verify_holdout_manifest:
        r0 = subprocess.run(
            [sys.executable, str(_REPO / "training/scripts/holdout_guard.py"), "--verify"],
            cwd=str(_REPO),
            env={**os.environ},
        )
        if r0.returncode != 0:
            return r0.returncode

    if not args.skip_guard and existing:
        r = subprocess.run(
            [sys.executable, str(_REPO / "training/scripts/holdout_guard.py"), "--check-training-data"]
            + [str(p) for p in existing],
            cwd=str(_REPO),
            env={**os.environ},
        )
        if r.returncode != 0:
            logging.error("holdout_guard 未通过，请检查训练 JSON 是否含 Holdout symbol")
            return r.returncode

    print(
        "\n[后续] 若 L3 要求 DVC：在 training/ 目录执行 ``dvc add`` / ``dvc push``；"
        "WandB：``export CRYO_GUARD_WANDB=1`` 后重跑蒸馏。\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
