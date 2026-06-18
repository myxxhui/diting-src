"""ARQ 常驻 Worker · 消费 Cron enqueue 与旁路任务。

[Ref: 29_ §1.4 · §8]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from apps.copilot.services.queue.settings import max_jobs, redis_settings, retry_backoff

logger = logging.getLogger("copilot.arq_worker")

async def smoke_ping(ctx: dict[str, Any], message: str = "pong") -> dict[str, Any]:
    """基础设施 smoke task。"""
    return {"status": "ok", "message": message}


# 日频 EOD job → 对应 backfill job 映射（缺交易日时自动补跑）
_GAP_BACKFILL_MAP: dict[str, str] = {
    "l4-smart-money-eod": "l4-smart-money-backfill",
    "l2-super-order-eod": "l2-super-order-backfill",
}
# 日频 job 的容忍间隔（工作日）：超过此天数视为 gap
_GAP_GRACE_DAYS: int = 2


async def _detect_and_backfill_gaps(
    session,
    job_id: str,
    symbols: list[str],
    source: str,
) -> list[dict[str, Any]]:
    """检测 watermark gap 并自动入队回填任务。

    对日频 EOD job，若 last_success_at 距今超过 2 个工作日，
    自动 enqueue 对应的 backfill job 补跑缺失数据。
    [Ref: 29_ §2 · scheduler gap recovery]
    """
    from datetime import date, datetime, timedelta

    from apps.copilot.db.models import ExecutingT0SyncWatermark

    backfill_job = _GAP_BACKFILL_MAP.get(job_id)
    if not backfill_job:
        return []

    results: list[dict[str, Any]] = []
    now = datetime.utcnow()
    for sym in symbols:
        wm = await session.get(ExecutingT0SyncWatermark, (job_id, sym))
        if wm is None or wm.last_success_at is None:
            continue
        days_since = (now - wm.last_success_at).days
        if days_since <= _GAP_GRACE_DAYS:
            continue

        logger.info(
            "gap 检测 job_id=%s symbol=%s 上次成功=%s 距今%d天 → 自动回填 %s",
            job_id, sym,
            wm.last_success_at.strftime("%Y-%m-%d") if wm.last_success_at else "?",
            days_since,
            backfill_job,
        )
        from apps.copilot.services.queue.enqueue import close_arq_pool, enqueue_executing_job

        try:
            arq_jid = await enqueue_executing_job(backfill_job, symbol=sym, source=f"{source}:gap")
            results.append(
                {
                    "action": "gap_backfill",
                    "backfill_job": backfill_job,
                    "symbol": sym,
                    "arq_job_id": arq_jid,
                    "days_since_last": days_since,
                }
            )
        except Exception:
            logger.exception("gap enqueue 失败 job=%s sym=%s", backfill_job, sym)
        finally:
            await close_arq_pool()

    return results


async def collect_executing_job(
    ctx: dict[str, Any],
    job_id: str,
    symbol: str | None = None,
    source: str = "arq",
) -> dict[str, Any]:
    """消费 executing_t0 任务 · 含自动 gap 检测与回填。

    [Ref: 29_ §1.4 · §6.2]
    """
    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.modules.executing.jobs_runner import run_job
    from apps.copilot.modules.executing.universe import load_executing_collect_symbols

    await init_db()
    gap_results: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as session:
        # 1. gap 检测（仅日频 job）
        try:
            syms = [symbol.zfill(6)[-6:]] if symbol else await load_executing_collect_symbols(session)
            gap_results = await _detect_and_backfill_gaps(session, job_id, syms, source)
        except Exception:
            logger.exception("gap 检测失败 job_id=%s（非阻塞）", job_id)
            await session.rollback()

        # 2. 执行主任务
        try:
            result = await run_job(session, job_id, symbol=symbol)
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.exception("executing job 失败 job_id=%s", job_id)
            return {"job_id": job_id, "status": "error", "source": source, "error": str(exc)[:300]}

    result.setdefault("source", source)
    if gap_results:
        result["gap_backfills"] = gap_results
    return result


async def collect_radar_job(
    ctx: dict[str, Any],
    job_id: str,
    symbol: str | None = None,
    source: str = "arq",
) -> dict[str, Any]:
    """消费 radar_t0 Cron enqueue。"""
    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.modules.radar.t0.jobs.runner import run_job
    from apps.copilot.services.redis_wait import wait_for_sync_redis

    await init_db()
    redis_client = wait_for_sync_redis()
    async with AsyncSessionLocal() as session:
        try:
            result = await run_job(session, job_id, redis_client=redis_client, symbol=symbol)
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.exception("radar job 失败 job_id=%s", job_id)
            return {"job_id": job_id, "status": "error", "source": source, "error": str(exc)[:300]}
    result.setdefault("source", source)
    return result


async def collect_z0_job(
    ctx: dict[str, Any],
    job_id: str,
    source: str = "arq",
    run_id: str | None = None,
) -> dict[str, Any]:
    """消费 Z0 段 A 采集 enqueue。"""
    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.metrics.z0_runner import run_z0_job
    from apps.copilot.services.redis_wait import wait_for_sync_redis

    await init_db()
    redis_client = wait_for_sync_redis()
    async with AsyncSessionLocal() as session:
        try:
            result = await run_z0_job(session, job_id, redis_client, run_id=run_id)
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.exception("Z0 job 失败 job_id=%s", job_id)
            return {"job_id": job_id, "status": "error", "source": source, "error": str(exc)[:300]}
    result.setdefault("source", source)
    return result


class WorkerSettings:
    functions = [smoke_ping, collect_executing_job, collect_radar_job, collect_z0_job]
    redis_settings = redis_settings()
    max_jobs = max_jobs()
    job_timeout = 3600
    max_tries = len(retry_backoff()) + 1
    retry_jobs = True


async def _check_connections() -> int:
    """§9 #6 · Worker 启动前连通性检查。"""
    import redis.asyncio as aioredis

    from apps.copilot.services.deepsea.policy_reader import check_deepsea_pg_ready

    rs = redis_settings()
    dsn = f"redis://{rs.host}:{rs.port}/{rs.database}"
    print(f"检查 ARQ Redis: {dsn}")
    client = aioredis.from_url(dsn, decode_responses=True)
    try:
        pong = await client.ping()
        print(f"  Redis PING → {pong!r}")
    finally:
        await client.aclose()

    ds_health = check_deepsea_pg_ready()
    print(f"  DeepSea PG → {ds_health.get('status', 'unknown')}")
    if ds_health.get("error"):
        print(f"  DeepSea 说明: {ds_health['error']}")

    pool = None
    try:
        from apps.copilot.services.queue.enqueue import enqueue_smoke_ping, get_arq_pool

        pool = await get_arq_pool()
        jid = await enqueue_smoke_ping("check")
        print(f"  ARQ enqueue smoke_ping → job_id={jid}")
    finally:
        if pool is not None:
            await pool.close()

    print("✅ ARQ 基础设施检查通过")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Copilot ARQ Worker [Ref: 29_]")
    parser.add_argument("--check", action="store_true", help="连通性检查（不入队消费）")
    args = parser.parse_args(argv)

    if args.check:
        return asyncio.run(_check_connections())

    logger.info("启动 ARQ Worker · max_jobs=%s", max_jobs())
    from arq import run_worker

    run_worker(WorkerSettings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
