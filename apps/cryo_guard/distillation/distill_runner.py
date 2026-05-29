"""蒸馏主流程：候选 → Teacher → 落库（同步 SQLite）。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_03_Teacher蒸馏.md]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.cryo_guard.db.models import Announcement, FinancialReport, RelatedPartyRaw, TeacherDistill
from apps.cryo_guard.db.sync_session import session_scope
from apps.cryo_guard.distillation.prompts import build_prompt
from apps.cryo_guard.distillation.teacher_client import TeacherClient, parse_teacher_output

logger = logging.getLogger(__name__)

TARGETS = {"financial_fraud": 1500, "shareholder_integrity": 1000, "related_party": 1000}


def _maybe_wandb_log(
    engine: str,
    written: int,
    parse_fail: int,
    latency_ms: int,
    tokens_out: int,
) -> None:
    if os.environ.get("CRYO_GUARD_WANDB") != "1":
        return
    try:
        import wandb

        if wandb.run is None:
            return
        wandb.log(
            {
                f"distill/{engine}/written": written,
                f"distill/{engine}/parse_fail_rate": parse_fail / max(written, 1),
                f"distill/{engine}/latency_ms": latency_ms,
                f"distill/{engine}/tokens_out": tokens_out,
            }
        )
    except Exception:
        pass


def _holdout_root() -> Path:
    env = os.environ.get("CRYO_HOLDOUT_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "training" / "data" / "holdout"


def _holdout_syms() -> set[str]:
    syms: set[str] = set()
    root = _holdout_root()
    if not root.is_dir():
        return syms
    for f in root.glob("H*.json"):
        try:
            syms.add(json.loads(f.read_text(encoding="utf-8"))["symbol"])
        except (KeyError, json.JSONDecodeError, OSError):
            continue
    return syms


def _yoy(cur: Any, prev: Any) -> Any:
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / prev


def _hash_case(engine: str, symbol: str, period: str, payload: dict) -> str:
    s = f"{engine}|{symbol}|{period}|{json.dumps(payload, sort_keys=True)}"
    return hashlib.sha256(s.encode()).hexdigest()


def _peer_median(session: Session, report_date: Any, field: str) -> float | None:
    col = getattr(FinancialReport, field)
    return session.scalar(select(func.avg(col)).where(FinancialReport.report_date == report_date))


def iter_financial_candidates(session: Session, holdout_syms: set[str]) -> Iterator[dict]:
    stmt = (
        select(FinancialReport)
        .where(FinancialReport.report_type == "annual")
        .order_by(FinancialReport.report_date.asc())
    )
    for fr in session.scalars(stmt):
        if fr.symbol in holdout_syms:
            continue
        if fr.revenue is None or fr.net_profit is None:
            continue
        prev = session.scalar(
            select(FinancialReport)
            .where(
                FinancialReport.symbol == fr.symbol,
                FinancialReport.report_date < fr.report_date,
                FinancialReport.report_type == "annual",
            )
            .order_by(FinancialReport.report_date.desc())
            .limit(1)
        )
        gm_cur = fr.gross_margin
        if gm_cur is None and fr.revenue and fr.revenue != 0 and fr.gross_profit is not None:
            gm_cur = fr.gross_profit / fr.revenue
        gm_prev = prev.gross_margin if prev else None
        if gm_prev is None and prev and prev.revenue and prev.revenue != 0 and prev.gross_profit is not None:
            gm_prev = prev.gross_profit / prev.revenue
        ctx = {
            "company_name": fr.company_name,
            "symbol": fr.symbol,
            "report_date": str(fr.report_date),
            "cash_cur": fr.cash_and_equivalents,
            "cash_prev": prev.cash_and_equivalents if prev else None,
            "cash_yoy": _yoy(fr.cash_and_equivalents, prev.cash_and_equivalents if prev else None),
            "short_debt_cur": fr.short_term_debt,
            "short_debt_prev": prev.short_term_debt if prev else None,
            "long_debt_cur": fr.long_term_debt,
            "long_debt_prev": prev.long_term_debt if prev else None,
            "ar_cur": fr.accounts_receivable,
            "ar_prev": prev.accounts_receivable if prev else None,
            "ar_yoy": _yoy(fr.accounts_receivable, prev.accounts_receivable if prev else None),
            "inv_cur": fr.inventory,
            "inv_prev": prev.inventory if prev else None,
            "inv_yoy": _yoy(fr.inventory, prev.inventory if prev else None),
            "rev_cur": fr.revenue,
            "rev_prev": prev.revenue if prev else None,
            "rev_yoy": _yoy(fr.revenue, prev.revenue if prev else None),
            "cost_cur": fr.cost_of_revenue,
            "cost_prev": prev.cost_of_revenue if prev else None,
            "gm_cur": gm_cur,
            "gm_prev": gm_prev,
            "np_cur": fr.net_profit,
            "np_prev": prev.net_profit if prev else None,
            "ocf_cur": fr.operating_cash_flow,
            "ocf_prev": prev.operating_cash_flow if prev else None,
            "rd_cur": fr.rd_expense,
            "rd_prev": prev.rd_expense if prev else None,
            "rdcap_cur": fr.rd_capitalized,
            "rdcap_prev": prev.rd_capitalized if prev else None,
            "peer_gm": _peer_median(session, fr.report_date, "gross_margin"),
            "peer_ar_turn": _peer_median(session, fr.report_date, "receivable_turnover"),
            "peer_inv_turn": _peer_median(session, fr.report_date, "inventory_turnover"),
        }
        yield {
            "engine": "financial_fraud",
            "symbol": fr.symbol,
            "period": str(fr.report_date),
            "ctx": ctx,
        }


def iter_shareholder_candidates(session: Session, holdout_syms: set[str]) -> Iterator[dict]:
    rows = session.execute(
        select(Announcement.symbol, Announcement.company_name)
        .where(Announcement.ann_type.in_(("增持", "减持", "业绩", "质押", "战略")))
        .distinct()
    ).all()
    for symbol, name in rows:
        if symbol in holdout_syms:
            continue
        anns = (
            session.scalars(
                select(Announcement).where(Announcement.symbol == symbol).order_by(Announcement.ann_date)
            )
        ).all()
        if len(anns) < 3:
            continue
        commitments = "\n".join(f"- [{a.ann_date}] [{a.ann_type}] {a.title}" for a in anns[:30])
        ctx = {
            "company_name": name or symbol,
            "symbol": symbol,
            "window_start": str(anns[0].ann_date),
            "window_end": str(anns[-1].ann_date),
            "commitments_block": commitments,
            "actual_holdings_changes": "（stub）",
            "actual_vs_promised_perf": "（stub）",
            "pledge_changes": "（stub）",
            "strategy_progress": "（stub）",
        }
        yield {
            "engine": "shareholder_integrity",
            "symbol": symbol,
            "period": str(anns[-1].ann_date),
            "ctx": ctx,
        }


def iter_related_party_candidates(session: Session, holdout_syms: set[str]) -> Iterator[dict]:
    rows = session.execute(
        select(
            RelatedPartyRaw.symbol,
            RelatedPartyRaw.company_name,
            RelatedPartyRaw.report_year,
        ).distinct()
    ).all()
    for symbol, name, year in rows:
        if symbol in holdout_syms:
            continue
        rrows = (
            session.scalars(
                select(RelatedPartyRaw).where(
                    RelatedPartyRaw.symbol == symbol,
                    RelatedPartyRaw.report_year == year,
                )
            )
        ).all()
        if not rrows:
            continue
        table_lines = []
        total_amount = sum((r.amount or 0) for r in rrows) or 1.0
        for r in rrows[:50]:
            pct = (r.amount or 0) / total_amount * 100
            table_lines.append(
                f"| {r.party_name[:24]} | {r.relationship or '-'} | "
                f"{r.transaction_type or '-'} | {r.amount or 0:.0f} | {pct:.1f}% | "
                f"{r.pricing_method or '-'} |"
            )
        ctx = {
            "company_name": name or symbol,
            "symbol": symbol,
            "report_period": f"{year}-12-31",
            "equity_block": "（stub）",
            "rp_table": "\n".join(table_lines),
            "anomaly_signals": "（stub）",
        }
        yield {
            "engine": "related_party",
            "symbol": symbol,
            "period": f"{year}-12-31",
            "ctx": ctx,
        }


ITER_MAP = {
    "financial_fraud": iter_financial_candidates,
    "shareholder_integrity": iter_shareholder_candidates,
    "related_party": iter_related_party_candidates,
}


def run(
    engine: str,
    target_count: int,
    *,
    limit: int | None = None,
    dry_run: bool = False,
) -> int:
    """返回本 run 新增写入条数。"""
    teacher = TeacherClient()
    holdout_syms = _holdout_syms()
    written = 0
    parse_fail = 0

    with session_scope() as session:
        existing = session.scalar(
            select(func.count()).select_from(TeacherDistill).where(TeacherDistill.engine_name == engine)
        )
        existing = existing or 0
        remaining = max(0, target_count - int(existing))
        if limit is not None:
            remaining = min(remaining, limit)
        if remaining == 0:
            logger.info("[%s] 已达目标或 limit=0，跳过", engine)
            return 0

        if os.environ.get("CRYO_GUARD_WANDB") == "1" and not dry_run:
            try:
                import wandb

                if wandb.run is None:
                    wandb.init(
                        project="diting-cryo-guard",
                        name=f"distill_{engine}",
                        config={"target": target_count, "limit": limit},
                    )
            except Exception as exc:
                logger.warning("wandb init 跳过: %s", exc)

        for cand in ITER_MAP[engine](session, holdout_syms):
            if written >= remaining:
                break
            instruction, prompt = build_prompt(cand["engine"], cand["ctx"])
            case_hash = _hash_case(engine, cand["symbol"], cand["period"], cand["ctx"])
            dup = session.scalar(
                select(TeacherDistill.id).where(
                    TeacherDistill.engine_name == engine,
                    TeacherDistill.symbol == cand["symbol"],
                    TeacherDistill.report_period == cand["period"],
                    TeacherDistill.case_hash == case_hash,
                )
            )
            if dup:
                continue
            if dry_run:
                logger.info(
                    "[dry-run] %s %s %s prompt_len=%s",
                    engine,
                    cand["symbol"],
                    cand["period"],
                    len(prompt),
                )
                written += 1
                continue

            resp = teacher.call(engine, instruction, prompt)
            parsed, status = parse_teacher_output(resp.raw_text)
            if status != "ok":
                parse_fail += 1
            out_text = json.dumps(parsed, ensure_ascii=False) if parsed else resp.raw_text
            row = TeacherDistill(
                engine_name=engine,
                symbol=cand["symbol"],
                company_name=str(cand["ctx"].get("company_name", "")),
                report_period=cand["period"],
                case_hash=case_hash,
                instruction=instruction,
                input=prompt,
                output=out_text,
                teacher_model=resp.model_id,
                teacher_latency_ms=resp.latency_ms,
                teacher_tokens_in=resp.tokens_in,
                teacher_tokens_out=resp.tokens_out,
                parse_status=status,
                metadata_json={"engine": engine},
            )
            session.add(row)
            session.commit()
            written += 1
            logger.info("[%s] wrote %s %s parse=%s", engine, cand["symbol"], cand["period"], status)
            if written == 1 or written % 10 == 0:
                _maybe_wandb_log(engine, written, parse_fail, resp.latency_ms, resp.tokens_out)

            if written and written % 50 == 0 and parse_fail / written > 0.10:
                logger.error("[%s] JSON 解析失败率 > 10%%，停止", engine)
                break

    if os.environ.get("CRYO_GUARD_WANDB") == "1":
        try:
            import wandb

            if wandb.run is not None:
                wandb.finish()
        except Exception:
            pass

    return written


def main() -> None:
    ap = argparse.ArgumentParser(description="cryo_guard Teacher 蒸馏 runner（阶段 A：--limit + MOCK）")
    ap.add_argument("--engine", choices=list(TARGETS.keys()), required=True)
    ap.add_argument("--target", type=int, default=None, help="目标总条数（按库内已有扣减）")
    ap.add_argument("--limit", type=int, default=None, help="本次最多新增条数")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    target = args.target if args.target is not None else TARGETS[args.engine]

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    n = run(args.engine, target, limit=args.limit, dry_run=args.dry_run)
    logger.info("done engine=%s new_rows=%s", args.engine, n)


if __name__ == "__main__":
    main()
