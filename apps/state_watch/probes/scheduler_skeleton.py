"""APScheduler 脚手架(本 step 注册 P3/P4 等 Interval/Cron 任务).

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_03]
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from apps.state_watch.probes.event import EventProbe
from apps.state_watch.probes.financial import FinancialProbe
from apps.state_watch.probes.news import NewsProbe
from apps.state_watch.probes.price import PriceProbe

logger = logging.getLogger(__name__)

_SAMPLE_SYMBOLS = ["600519", "000001", "300750"]


def build_scheduler() -> AsyncIOScheduler:
    sched = AsyncIOScheduler()
    price = PriceProbe()
    event = EventProbe()
    news = NewsProbe()
    fin = FinancialProbe()

    sched.add_job(_run_all, IntervalTrigger(minutes=30), kwargs={"probe": price, "tag": "price"}, id="price-30m")
    sched.add_job(_run_all, IntervalTrigger(hours=1), kwargs={"probe": news, "tag": "news"}, id="news-1h")
    sched.add_job(_run_all, IntervalTrigger(hours=6), kwargs={"probe": event, "tag": "event"}, id="event-6h")
    sched.add_job(_run_all, CronTrigger(hour=9, minute=0), kwargs={"probe": fin, "tag": "financial"}, id="fin-daily")
    return sched


async def _run_all(probe, tag: str) -> None:
    for symbol in _SAMPLE_SYMBOLS:
        result = await probe.fetch(symbol)
        logger.info(
            "[%s] %s success=%s elapsed_ms=%.1f data_keys=%s",
            tag,
            symbol,
            result.success,
            result.elapsed_ms,
            list(result.data.keys()),
        )


async def run_once() -> None:
    """一次性触发所有探针 ×3 标的,用于本 step 验证."""
    for cls, tag in [
        (PriceProbe, "price"),
        (EventProbe, "event"),
        (NewsProbe, "news"),
        (FinancialProbe, "financial"),
    ]:
        await _run_all(cls(), tag)


async def _run_loop() -> None:
    sched = build_scheduler()
    sched.start()
    logger.info("scheduler started; Ctrl+C to exit")
    try:
        await asyncio.Event().wait()
    finally:
        sched.shutdown(wait=False)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="一次性触发,不进入调度循环")
    args = parser.parse_args()
    if args.once:
        asyncio.run(run_once())
        return
    try:
        asyncio.run(_run_loop())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
