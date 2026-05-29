"""行情刷新调度器(APScheduler).

[Ref: 03_/04_维度四/.../step_02]
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime
from typing import Callable, Optional, Protocol

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

from apps.exit_engine.config import settings
from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.services.buffer_manager import BufferManager

logger = logging.getLogger(__name__)


class SupportsFetchBatch(Protocol):
    def fetch_batch(self, symbols: list[str]) -> dict[str, float]: ...


def refresh_quotes_once(
    user_id: str = "default",
    fetcher: Optional[SupportsFetchBatch] = None,
    on_update: Optional[Callable[[dict[str, float], int], None]] = None,
) -> tuple[int, int]:
    session = SessionLocal()
    try:
        repo = HoldingsRepository(session)
        positions = repo.list_active(user_id=user_id)
        symbols = [p.symbol for p in positions]
        if not symbols:
            logger.info("[%s] 无活跃持仓,跳过", datetime.now().isoformat(timespec="seconds"))
            return 0, 0
        use_fetcher = fetcher
        if use_fetcher is None:
            from apps.exit_engine.data.quote_fetcher import build_fetcher

            use_fetcher = build_fetcher(use_mock=False)
        quotes = use_fetcher.fetch_batch(symbols)
        updated = repo.bulk_update_quotes(quotes, user_id=user_id)
        logger.info(
            "[%s] 刷新行情 总持仓=%s 更新成功=%s",
            datetime.now().isoformat(timespec="seconds"),
            len(positions),
            updated,
        )
        if on_update:
            on_update(quotes, updated)
        return len(positions), updated
    finally:
        session.close()


def expire_due_signals_once() -> int:
    """执行一次缓冲期到期扫描;返回到期数量(供监控)。"""
    session = SessionLocal()
    try:
        buffer = BufferManager(session)
        fired = buffer.expire_due()
        if fired:
            logger.info("buffer 到期 %s 笔:%s", len(fired), [s.audit_id for s in fired])
        return len(fired)
    finally:
        session.close()


def start_background_scheduler(user_id: str = "default") -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        refresh_quotes_once,
        trigger="interval",
        minutes=settings.quote_refresh_minutes,
        kwargs={"user_id": user_id},
        id="quote_refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        expire_due_signals_once,
        trigger="interval",
        minutes=1,
        id="buffer_expire",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "BackgroundScheduler 启动:行情 %s 分钟,缓冲到期 1 分钟",
        settings.quote_refresh_minutes,
    )
    return scheduler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="只跑一次刷新后退出")
    parser.add_argument("--user-id", default="default")
    parser.add_argument("--mock", action="store_true", help="使用 mock 行情")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    from apps.exit_engine.data.quote_fetcher import build_fetcher

    fetcher = build_fetcher(use_mock=args.mock)

    if args.once:
        total, updated = refresh_quotes_once(user_id=args.user_id, fetcher=fetcher)
        print(f"刷新完成: total={total} updated={updated}")
        return

    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        refresh_quotes_once,
        trigger="interval",
        minutes=settings.quote_refresh_minutes,
        kwargs={"user_id": args.user_id, "fetcher": fetcher},
        id="quote_refresh",
        max_instances=1,
        coalesce=True,
    )
    print(f"BlockingScheduler 启动,每 {settings.quote_refresh_minutes} 分钟刷新一次")
    scheduler.start()


if __name__ == "__main__":
    main()
