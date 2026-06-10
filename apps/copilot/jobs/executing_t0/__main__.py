"""python -m apps.copilot.jobs.executing_t0 <job_id> | --status

[Ref: 28_ §4.4]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("executing_t0.job")


async def _main_async(
    job_id: str | None,
    *,
    status: bool,
    symbol: str | None,
    enqueue: bool,
) -> int:
    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.modules.executing.jobs_runner import run_job
    from apps.copilot.modules.executing.pipeline_status import build_sync_status

    await init_db()

    if enqueue:
        if not job_id:
            logger.error("缺少 job_id")
            return 2
        from apps.copilot.services.queue.enqueue import close_arq_pool, enqueue_executing_job

        try:
            arq_job_id = await enqueue_executing_job(job_id, symbol=symbol, source="cron")
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
            out = await build_sync_status(session)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if not job_id:
        logger.error("缺少 job_id")
        return 2

    async with AsyncSessionLocal() as session:
        try:
            result = await run_job(session, job_id, symbol=symbol)
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.exception("job failed")
            print(json.dumps({"job_id": job_id, "status": "error", "error": str(exc)[:300]}))
            return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in ("ok", "skip") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="执行中 T0 CronJob / bootstrap")
    parser.add_argument("job_id", nargs="?", help="bootstrap-sync | daily-pipeline | collect-once | …")
    parser.add_argument("--status", action="store_true", help="executing-pipeline-status")
    parser.add_argument(
        "--enqueue",
        action="store_true",
        help="仅入队 ARQ（CronJob 轻量模式 · [Ref: 29_ §2]）",
    )
    parser.add_argument("--symbol", default=None, help="单标的，如 601138")
    args = parser.parse_args(argv)
    return asyncio.run(
        _main_async(
            args.job_id,
            status=args.status,
            symbol=args.symbol,
            enqueue=args.enqueue,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
