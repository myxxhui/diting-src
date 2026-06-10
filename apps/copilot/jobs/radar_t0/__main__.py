"""雷达 T0 CronJob / bootstrap CLI 入口。

用法:
  python -m apps.copilot.jobs.radar_t0 bars-reconcile-daily
  python -m apps.copilot.jobs.radar_t0 bootstrap-sync
  python -m apps.copilot.jobs.radar_t0 --status

[Ref: 27_ §2.8.1]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("radar_t0.job")


async def _main_async(
    job_id: str | None,
    *,
    status: bool,
    force: bool,
    enqueue: bool,
) -> int:
    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.modules.radar.t0.jobs.runner import run_job
    from apps.copilot.modules.radar.t0.jobs.status import build_pipeline_status

    await init_db()

    if enqueue:
        if not job_id:
            logger.error("缺少 job_id")
            return 2
        from apps.copilot.services.queue.enqueue import close_arq_pool, enqueue_radar_job

        try:
            arq_job_id = await enqueue_radar_job(job_id, source="cron")
            print(
                json.dumps(
                    {"job_id": job_id, "status": "enqueued", "arq_job_id": arq_job_id},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        finally:
            await close_arq_pool()

    if status:
        async with AsyncSessionLocal() as session:
            out = await build_pipeline_status(session)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        stale_jobs = [j["job_id"] for j in out["jobs"] if j.get("stale")]
        if stale_jobs:
            logger.warning("stale jobs: %s", ", ".join(stale_jobs))
        return 0

    if not job_id:
        logger.error("缺少 job_id")
        return 2

    from apps.copilot.services.redis_wait import wait_for_sync_redis

    redis_client = wait_for_sync_redis()
    async with AsyncSessionLocal() as session:
        try:
            result = await run_job(session, job_id, redis_client=redis_client, force=force)
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.exception("job failed")
            print(json.dumps({"job_id": job_id, "status": "error", "error": str(exc)[:300]}))
            return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in ("ok", "skip", "fresh") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="雷达 T0 CronJob / bootstrap")
    parser.add_argument("job_id", nargs="?", help="§2.8.2 job_id，如 bars-reconcile-daily")
    parser.add_argument("--status", action="store_true", help="输出 radar-pipeline-status")
    parser.add_argument("--force", action="store_true", help="bootstrap 强制补跑")
    parser.add_argument(
        "--enqueue",
        action="store_true",
        help="仅入队 ARQ（CronJob 轻量模式 · [Ref: 29_ §2]）",
    )
    args = parser.parse_args(argv)
    return asyncio.run(
        _main_async(
            args.job_id,
            status=args.status,
            force=args.force,
            enqueue=args.enqueue,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
