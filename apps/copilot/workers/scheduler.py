"""Copilot 内部调度器 · APScheduler 常驻进程。

替代 K8s CronJob：常驻进程内存定时 → ARQ enqueue → ARQ Worker 消费。
[Ref: 29_ §1.4 · §6.2 To-Be · §7 Phase 1]
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from apps.copilot.services.queue.settings import arq_redis_dsn

logger = logging.getLogger("copilot.scheduler")

# ── JL4 / JL3 采集调度表 ──────────────────────────────────────
# 每个条目：job_id、cron 表达式、时区、说明
# 首次/增量数据量见文档末尾的调度表

DEFAULT_SCHEDULE: list[dict] = [
    # ── 盘中高频 ──
    {"job_id": "quote-intraday",          "cron": "*/5 9-14 * * 1-5",  "tz": "Asia/Shanghai"},
    {"job_id": "quote-intraday-close",    "cron": "0 15 * * 1-5",     "tz": "Asia/Shanghai"},
    {"job_id": "l4-vol-div-15m",          "cron": "0,15,30,45 10-11,13-14 * * 1-5", "tz": "Asia/Shanghai"},
    {"job_id": "l4-vol-div-15m-open",     "cron": "45 9 * * 1-5",     "tz": "Asia/Shanghai"},
    {"job_id": "l4-vol-div-15m-close",    "cron": "0 15 * * 1-5",     "tz": "Asia/Shanghai"},

    # ── L4 日频 EOD ──
    {"job_id": "l4-atr-bars-sync",        "cron": "0 16 * * 1-5",     "tz": "Asia/Shanghai"},
    {"job_id": "l4-smart-money-eod",      "cron": "0 16 * * 1-5",     "tz": "Asia/Shanghai"},
    {"job_id": "l4-smart-money-backfill", "cron": "0 14 * * 1-5",     "tz": "Asia/Shanghai"},
    {"job_id": "l2-super-order-eod",      "cron": "0 17 * * 1-5",     "tz": "Asia/Shanghai"},
    {"job_id": "l2-super-order-backfill", "cron": "0 14 * * 1-5",     "tz": "Asia/Shanghai"},
    {"job_id": "l4-turnover-accel-eod",   "cron": "30 15 * * 1-5",    "tz": "Asia/Shanghai"},
    {"job_id": "l4-beta-correlation-eod", "cron": "30 15 * * 1-5",    "tz": "Asia/Shanghai"},
    {"job_id": "l4-block-trade-eod",      "cron": "0 18 * * 1-5",     "tz": "Asia/Shanghai"},
    {"job_id": "l4-retail-concentration-eod", "cron": "30 20 * * 1-5","tz": "Asia/Shanghai"},
    {"job_id": "l4-insider-sell-eod",     "cron": "30 20 * * 1-5",    "tz": "Asia/Shanghai"},

    # ── 盘前 T+1 ──
    {"job_id": "l4-margin-skew-morning",  "cron": "30 8 * * 2-6",     "tz": "Asia/Shanghai"},
    {"job_id": "l4-etf-redemption-morning","cron": "30 8 * * 2-6",     "tz": "Asia/Shanghai"},

    # ── L3 专用 ──
    {"job_id": "l3-fii-twse-monthly",     "cron": "0 8 5-12 * *",     "tz": "Asia/Shanghai"},
    {"job_id": "l3-fii-odm-quarterly",    "cron": "0 20 * * 1-5",     "tz": "Asia/Shanghai"},
    {"job_id": "l3-fii-gb200-milestone",  "cron": "0 17 * * 1-5",     "tz": "Asia/Shanghai"},

    # ── 日终聚合管线 ──
    {"job_id": "daily-pipeline",          "cron": "0 19 * * 1-5",     "tz": "Asia/Shanghai"},
]

# 环境变量覆盖：COPILOT_SCHEDULER_DISABLED_JOBS=job1,job2
_DISABLED = set(
    j.strip() for j in os.environ.get("COPILOT_SCHEDULER_DISABLED_JOBS", "").split(",") if j.strip()
)


def _cron_to_minutes(cron_expr: str) -> float:
    """估算 cron 触发的间隔分钟数（用于 misfire_grace_time）。"""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return 15  # 默认 15 分钟
    minute_field = parts[0]
    if minute_field == "*":
        return 1
    if "/" in minute_field:
        return int(minute_field.split("/")[1])
    if minute_field.startswith("*/"):
        return int(minute_field[2:])
    commas = [int(x) for x in minute_field.split(",") if x.isdigit()]
    if len(commas) >= 2:
        return max(1, min(abs(commas[i] - commas[i-1]) for i in range(1, len(commas))))
    if len(commas) == 1:
        # 单次触发（如 45 分）→ 取 hour 字段估算间隔
        hour_field = parts[1]
        if "/" in hour_field:
            return int(hour_field.split("/")[1]) * 60
        return 1440  # 日频
    return 15


async def _enqueue_executing_job(job_id: str) -> None:
    """调度器触发的轻量 enqueue（仅入队，不执行）。"""
    from apps.copilot.services.queue.enqueue import close_arq_pool, enqueue_executing_job

    try:
        arq_jid = await enqueue_executing_job(job_id, source="scheduler")
        logger.info("scheduler → enqueue %s arq_job=%s", job_id, arq_jid)
    except Exception:
        logger.exception("scheduler enqueue 失败 job_id=%s", job_id)
    finally:
        await close_arq_pool()


def build_scheduler() -> AsyncIOScheduler:
    """创建调度器（MemoryJobStore，replicas=1 无需 Redis 去重）。"""
    scheduler = AsyncIOScheduler(
        timezone=timezone.utc,
    )
    return scheduler


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """注册全部采集调度。"""
    registered = 0
    for job_def in DEFAULT_SCHEDULE:
        jid = job_def["job_id"]
        if jid in _DISABLED:
            logger.info("scheduler 禁用 job_id=%s (COPILOT_SCHEDULER_DISABLED_JOBS)", jid)
            continue
        cron_expr = job_def["cron"]
        grace_sec = int(_cron_to_minutes(cron_expr) * 60 * 2)  # 2 倍间隔作为容错
        trigger = CronTrigger.from_crontab(cron_expr, timezone=job_def.get("tz", "Asia/Shanghai"))
        scheduler.add_job(
            _enqueue_executing_job,
            trigger=trigger,
            args=[jid],
            id=f"executing:{jid}",
            name=f"executing-t0-{jid}",
            replace_existing=True,
            misfire_grace_time=max(grace_sec, 300),
            coalesce=True,
            max_instances=1,
        )
        registered += 1
        logger.info("scheduler 注册 job_id=%-35s cron=%-30s tz=%s", jid, cron_expr, job_def.get("tz", "UTC"))
    logger.info("scheduler 共注册 %d 个定时任务", registered)


async def _run_once_and_exit() -> None:
    """调度器仅运行一次：enqueue 当前时刻应触发的全部 job 后退出（用于 bootstrap 场景）。"""
    scheduler = build_scheduler()
    register_jobs(scheduler)
    scheduler.start()
    # 等待所有 misfire 任务提交
    await asyncio.sleep(5)
    # 立即触发 daily-pipeline（bootstrap 核心）
    await _enqueue_executing_job("daily-pipeline")
    await asyncio.sleep(2)
    scheduler.shutdown(wait=False)
    logger.info("scheduler bootstrap 完成")


async def _run_scheduler_forever() -> None:
    """启动调度器并永久运行。"""
    scheduler = build_scheduler()
    register_jobs(scheduler)
    logger.info("=" * 60)
    logger.info("Copilot 内部调度器启动 · 替代 K8s CronJob")
    logger.info("jobs=%d  disabled=%d", len(DEFAULT_SCHEDULE), len(_DISABLED))
    logger.info("=" * 60)

    scheduler.start()

    # 优雅退出
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.shutdown(wait=False)
        logger.info("scheduler 已停止")


def main(argv: list[str] | None = None) -> int:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Copilot 内部调度器 [Ref: 29_ §1.4 · §6.2]")
    parser.add_argument("--bootstrap", action="store_true", help="仅运行一次 bootstrap 后退出")
    args = parser.parse_args(argv)

    if args.bootstrap:
        asyncio.run(_run_once_and_exit())
        return 0

    asyncio.run(_run_scheduler_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
