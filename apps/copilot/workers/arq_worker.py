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


async def collect_executing_job(
    ctx: dict[str, Any],
    job_id: str,
    symbol: str | None = None,
    source: str = "arq",
) -> dict[str, Any]:
    """消费 executing_t0 Cron enqueue。"""
    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.modules.executing.jobs_runner import run_job

    await init_db()
    async with AsyncSessionLocal() as session:
        try:
            result = await run_job(session, job_id, symbol=symbol)
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.exception("executing job 失败 job_id=%s", job_id)
            return {"job_id": job_id, "status": "error", "source": source, "error": str(exc)[:300]}
    result.setdefault("source", source)
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


async def index_document(
    ctx: dict[str, Any],
    doc: dict[str, Any],
) -> dict[str, Any]:
    """低优先级 ES 索引（旁路 · 不阻塞主链）。"""
    from apps.copilot.services.search.doc_retriever import index_document as es_index

    doc_id = await es_index(doc)
    return {"status": "ok", "doc_id": doc_id}


class WorkerSettings:
    functions = [smoke_ping, collect_executing_job, collect_radar_job, index_document]
    redis_settings = redis_settings()
    max_jobs = max_jobs()
    job_timeout = 3600
    max_tries = len(retry_backoff()) + 1
    retry_jobs = True


async def _check_connections() -> int:
    """§9 #6 · Worker 启动前连通性检查。"""
    import redis.asyncio as aioredis

    from apps.copilot.services.search.doc_retriever import check_opensearch_health

    rs = redis_settings()
    dsn = f"redis://{rs.host}:{rs.port}/{rs.database}"
    print(f"检查 ARQ Redis: {dsn}")
    client = aioredis.from_url(dsn, decode_responses=True)
    try:
        pong = await client.ping()
        print(f"  Redis PING → {pong!r}")
    finally:
        await client.aclose()

    os_health = await check_opensearch_health()
    print(f"  OpenSearch health → {os_health.get('status', 'skipped')}")
    if os_health.get("error"):
        print(f"  OpenSearch 说明: {os_health['error']}")

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
