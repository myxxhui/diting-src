"""D2 step_04 CLI — 利润截留扫描仪剧本 + The Mapper 业绩弹性闸门。

用法:
  python scripts/deep_step04_run.py scan-all          # 对全 active 标的跑剧本
  python scripts/deep_step04_run.py quality-check     # §3.5 18 项质量矩阵检查
  python scripts/deep_step04_run.py mapper-run        # 对当日 Critic 通过簇跑 Mapper
  python scripts/deep_step04_run.py mapper-status     # 近 7 日 mapper_outputs 分布
  python scripts/deep_step04_run.py status            # 每 symbol 最近 scan_logs 摘要

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_04_利润截留扫描仪剧本.md §7.2]
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

# 确保根路径在 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# scan-all：全 active 标的跑利润截留扫描仪
# ---------------------------------------------------------------------------


async def _run_scan_all() -> None:
    from apps.common.holdings_sot import load_holdings_sot
    from apps.deep_strike.db.database import AsyncSessionLocal, init_db
    from apps.deep_strike.playbooks.profit_capture.playbook import ProfitCapturePlaybook

    await init_db()
    sot = load_holdings_sot()
    symbols = sot.active_symbols()
    if not symbols:
        print("⚠️  SoT 中无 active 标的，请检查 my_holdings.yaml")
        return

    pb = ProfitCapturePlaybook(session_factory=AsyncSessionLocal)
    total = len(symbols)
    proposed = watch = discard = 0
    for sym in symbols:
        try:
            r = await pb.scan(sym)
            if r.decision == "propose":
                proposed += 1
            elif r.decision == "watch":
                watch += 1
            else:
                discard += 1
            print(f"  {sym}: {r.decision} conf={r.confidence:.2f}")
        except Exception as exc:
            print(f"  {sym}: ❌ {exc}")
    print(f"\n✅ scan-all 完成 total={total} propose={proposed} watch={watch} discard={discard}")
    print("▶ 做了什么: 对全 active 标的跑利润截留扫描仪剧本")
    print(f"▶ 期望什么: ≥1 条 scan_logs 入库，至少 1 标的 score≥0.4")
    print(f"▶ 实际什么: propose={proposed} watch={watch}")


# ---------------------------------------------------------------------------
# quality-check：§3.5 质量矩阵
# ---------------------------------------------------------------------------


async def _run_quality_check() -> None:
    from sqlalchemy import func, select

    from apps.deep_strike.db.database import AsyncSessionLocal, init_db
    from apps.deep_strike.db.models import EvidenceRecord, MapperOutput, ScanLog

    await init_db()
    issues = 0
    async with AsyncSessionLocal() as session:
        # Q1: scan_logs 存在
        count = await session.scalar(select(func.count()).select_from(ScanLog))
        if not count:
            print("❌ Q1: scan_logs 空，请先跑 scan-all")
            issues += 1
        else:
            print(f"✅ Q1: scan_logs {count} 条")

        # Q2: 至少 1 条 decision=watch 或 propose
        watch_count = await session.scalar(
            select(func.count()).select_from(ScanLog).where(
                ScanLog.decision.in_(["propose", "watch"])
            )
        )
        if not watch_count:
            print("❌ Q2: 无 watch/propose 记录（score 全 <0.4）")
            issues += 1
        else:
            print(f"✅ Q2: watch+propose {watch_count} 条")

        # Q3: signals_json 非空
        no_signals = await session.scalar(
            select(func.count()).select_from(ScanLog).where(
                ScanLog.signals == None  # noqa: E711
            )
        )
        if no_signals:
            print(f"⚠️  Q3: {no_signals} 条 signals 为 null")
            issues += 1
        else:
            print("✅ Q3: signals_json 非空")

        # Q4: evidence_records physical 类型存在
        phys_count = await session.scalar(
            select(func.count()).select_from(EvidenceRecord).where(
                EvidenceRecord.evidence_type == "physical"
            )
        )
        print(f"{'✅' if phys_count else '⚠️ '} Q4: physical evidence_records {phys_count} 条")

        # Q5: physical_gate=True 记录
        pg_count = await session.scalar(
            select(func.count()).select_from(EvidenceRecord).where(
                EvidenceRecord.physical_gate.is_(True)
            )
        )
        print(f"{'✅' if pg_count else '⚠️ '} Q5: physical_gate=True {pg_count} 条")

        # Q6: mapper_outputs 存在
        mo_count = await session.scalar(select(func.count()).select_from(MapperOutput))
        print(f"{'✅' if mo_count else '⚠️ '} Q6: mapper_outputs {mo_count} 条")

    status = "✅ 全部通过" if issues == 0 else f"⚠️  {issues} 项不满足"
    print(f"\n质量检查结果: {status}")
    sys.exit(0 if issues == 0 else 1)


# ---------------------------------------------------------------------------
# mapper-run：对当日 Critic 通过簇跑 Mapper
# ---------------------------------------------------------------------------


def _run_mapper_run() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from apps.common.holdings_sot import load_holdings_sot
    from apps.deep_strike.config import settings
    from apps.deep_strike.events.publisher import get_publisher
    from apps.deep_strike.playbooks.the_mapper.mapper import run_mapper

    # 注意: Mapper 使用同步 session（纯规则，无 async 需求）
    sync_url = settings.db_url.replace("sqlite+aiosqlite", "sqlite")
    engine = create_engine(sync_url)

    sot = load_holdings_sot()
    symbols = sot.active_symbols()
    publisher = get_publisher(settings.redis_url)

    total_events = 0
    with Session(engine) as session:
        for sym in symbols:
            try:
                result = run_mapper(sym, session=session, publisher=publisher)
                total_events += result.events_emitted
                print(
                    f"  {sym}: clusters={result.total_clusters} "
                    f"proposed={result.proposed} dropped={result.dropped} "
                    f"events={result.events_emitted}"
                )
            except Exception as exc:
                print(f"  {sym}: ❌ {exc}")

    print(f"\n✅ mapper-run 完成: 总投递事件 {total_events}")
    print(f"▶ 做了什么: 对全 active 标的跑 The Mapper 弹性闸门")
    print(f"▶ 期望什么: physical_gate=True 簇各出 1 条 mapper_outputs")
    print(f"▶ 实际什么: total_events={total_events} local_pending={publisher.pending_count}")


# ---------------------------------------------------------------------------
# mapper-status：近 7 日 mapper_outputs 分布
# ---------------------------------------------------------------------------


async def _run_mapper_status() -> None:
    from sqlalchemy import func, select

    from apps.deep_strike.db.database import AsyncSessionLocal, init_db
    from apps.deep_strike.db.models import MapperOutput

    await init_db()
    since = date.today() - timedelta(days=7)
    async with AsyncSessionLocal() as session:
        rows = await session.scalars(
            select(MapperOutput)
            .where(MapperOutput.created_at >= since.isoformat())
            .order_by(MapperOutput.created_at.desc())
        )
        all_rows = list(rows.all())

    if not all_rows:
        print("⚠️  近 7 日无 mapper_outputs 记录")
        return

    by_tier: dict[str, dict[str, int]] = {}
    for r in all_rows:
        tier = r.market_cap_tier
        if tier not in by_tier:
            by_tier[tier] = {"proposed": 0, "dropped": 0, "pending": 0}
        key = r.status if r.status in by_tier[tier] else "pending"
        by_tier[tier][key] += 1

    print(f"近 7 日 mapper_outputs 分布（共 {len(all_rows)} 条）:")
    for tier, counts in by_tier.items():
        print(f"  {tier}: proposed={counts['proposed']} dropped={counts['dropped']}")


# ---------------------------------------------------------------------------
# status：每 symbol 最近 scan_logs 摘要
# ---------------------------------------------------------------------------


async def _run_status() -> None:
    from sqlalchemy import select

    from apps.deep_strike.db.database import AsyncSessionLocal, init_db
    from apps.deep_strike.db.models import ScanLog

    await init_db()
    async with AsyncSessionLocal() as session:
        rows = await session.scalars(
            select(ScanLog).order_by(ScanLog.created_at.desc()).limit(50)
        )
        all_rows = list(rows.all())

    if not all_rows:
        print("⚠️  scan_logs 为空，请先跑 scan-all")
        return

    latest: dict[str, ScanLog] = {}
    for r in all_rows:
        if r.symbol not in latest:
            latest[r.symbol] = r

    print("最近 scan_logs（每标的最新一条）:")
    for sym, r in sorted(latest.items()):
        print(f"  {sym}: {r.decision} conf={r.confidence:.2f} at={r.created_at.date()}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "scan-all":
        asyncio.run(_run_scan_all())
    elif cmd == "quality-check":
        asyncio.run(_run_quality_check())
    elif cmd == "mapper-run":
        _run_mapper_run()
    elif cmd == "mapper-status":
        asyncio.run(_run_mapper_status())
    elif cmd == "status":
        asyncio.run(_run_status())
    else:
        print(f"未知命令: {cmd}")
        print("用法: scan-all | quality-check | mapper-run | mapper-status | status")
        sys.exit(1)


if __name__ == "__main__":
    main()
