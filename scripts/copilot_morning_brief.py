#!/usr/bin/env python3
"""手动触发 W1+W2 合并持仓早报（与 8:00 cron 同逻辑）.

用法:
  cd diting-src && PYTHONPATH=. python3 scripts/copilot_morning_brief.py
  MORNING_BRIEF_RUN_PHASE=0 PYTHONPATH=. python3 scripts/copilot_morning_brief.py  # 跳过慢速阶段重算
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO = Path(__file__).resolve().parents[1]
load_dotenv(_REPO / ".env", override=False)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


async def _main() -> int:
    from apps.copilot.config import settings
    from apps.copilot.db.database import AsyncSessionLocal, init_db
    await init_db()
    # 复用 copilot lifespan 里的 dispatcher 组装
    from apps.copilot.services.alerts.channels.email import EmailChannel
    from apps.copilot.services.alerts.channels.telegram import TelegramChannel
    from apps.copilot.services.alerts.channels.wechat import WechatChannel
    from apps.copilot.services.alerts.dedup import AlertDeduper
    from apps.copilot.services.alerts.dispatcher import AlertDispatcher
    from apps.copilot.services.alerts.sla_monitor import SLAMonitor
    import redis.asyncio as redis_async

    redis_client = redis_async.from_url(settings.redis_url, decode_responses=True)
    channels = [
        WechatChannel(settings.wechat_webhook),
        TelegramChannel(settings.telegram_bot_token, settings.telegram_chat_id),
        EmailChannel(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            sender=settings.smtp_from,
            recipient=settings.smtp_to,
            use_ssl=settings.smtp_use_ssl,
        ),
    ]
    deduper = AlertDeduper(AsyncSessionLocal, window_seconds=settings.alert_dedup_window)
    sla = SLAMonitor(AsyncSessionLocal, red_sla_seconds=settings.alert_red_sla)
    dispatcher = AlertDispatcher(
        redis_client,
        AsyncSessionLocal,
        channels,
        deduper,
        sla,
    )
    from apps.copilot.scheduler.jobs.report_jobs import run_daily_for_all

    await run_daily_for_all(session_factory=AsyncSessionLocal, alert_dispatcher=dispatcher)
    await redis_client.aclose()
    print("✅ 合并早报已推送（若 SMTP 配置正确）")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
