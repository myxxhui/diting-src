"""python -m apps.copilot.jobs.z0_t0 <job_id> | --status | --enqueue

Z0 段 A 采集 · Redis ARQ 调度（Cron 仅 enqueue · Worker 消费）。
[Ref: 29_ §1.4 · 34_ §3.0b]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("z0_t0.job")


async def _main_async(
    job_id: str | None,
    *,
    status: bool,
    enqueue: bool,
) -> int:
    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.metrics.z0_runner import run_z0_job
    from apps.copilot.metrics.z0_status import build_z0_pipeline_status
    from apps.copilot.services.redis_wait import wait_for_sync_redis

    await init_db()
    redis = wait_for_sync_redis()

    if enqueue:
        if not job_id:
            logger.error("缺少 job_id")
            return 2
        from apps.copilot.services.queue.enqueue import close_arq_pool, enqueue_z0_job

        try:
            arq_job_id = await enqueue_z0_job(job_id, source="cron")
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
            out = await build_z0_pipeline_status(session, redis)
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0

    if not job_id:
        job_id = "z0-bootstrap-all"

    async with AsyncSessionLocal() as session:
        try:
            result = await run_z0_job(session, job_id, redis)
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.exception("Z0 job failed")
            print(json.dumps({"job_id": job_id, "status": "error", "error": str(exc)[:300]}))
            return 1

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") in ("ok", "ready") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Z0 段 A 采集 / wind_scan 合成")
    parser.add_argument(
        "job_id",
        nargs="?",
        help="z0-bootstrap-all | z0-m1-macro | z0-m5-liquidity | z0-policy-ingest | z0-m2-sector-heat | z0-m0-wind-scan",
    )
    parser.add_argument("--status", action="store_true", help="Z0 管线就绪状态")
    parser.add_argument(
        "--enqueue",
        action="store_true",
        help="仅入队 ARQ（CronJob 轻量模式 · [Ref: 29_ §2]）",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_main_async(args.job_id, status=args.status, enqueue=args.enqueue))


if __name__ == "__main__":
    raise SystemExit(main())
