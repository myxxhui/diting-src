#!/usr/bin/env python3
"""D0 step_05 · sell_signal → 邮件 e2e（与 D4 step_07 输出格式对齐）。

[Ref: 03_/00_维度零/.../step_05 §7.2 copilot-step05-sell-signal-e2e]
[Ref: 23_持仓标的售卖条件监控_需求实现表 · 必做②]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from apps.copilot.config import settings
from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.services.alerts.channels.email import EmailChannel
from apps.copilot.services.alerts.channels.telegram import TelegramChannel
from apps.copilot.services.alerts.channels.wechat import WechatChannel
from apps.copilot.services.alerts.dedup import AlertDeduper
from apps.copilot.services.alerts.dispatcher import (
    CONSUMER_GROUP,
    UPSTREAM_STREAMS,
    AlertDispatcher,
    _parse_stream_fields,
    map_event_to_alert,
)
from apps.copilot.services.alerts.sla_monitor import SLAMonitor

STREAM = "events:exit:sell_signal"


def _redis_url() -> str:
    return (
        os.environ.get("COPILOT_REDIS_URL")
        or os.environ.get("EXIT_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or "redis://127.0.0.1:6379/0"
    )


def _demo_payload(*, symbol: str, name: str, signal_type: str) -> dict[str, str]:
    """与 SellSignalEvent.to_stream_dict() 字段一致。"""
    now = datetime.now(timezone.utc).isoformat()
    advice_map = {
        "stop_loss": f"建议立即止损。{name} 已触及 -15% 止损线。（仅建议，须人工确认）",
        "take_profit": f"建议分批止盈。{name} 已达 +30% 止盈线。（仅建议，须人工确认）",
        "thesis_invalid": f"thesis 失效建议清仓。（仅建议，须人工确认）",
    }
    return {
        "symbol": symbol,
        "signal_type": signal_type,
        "trigger_price": "58.0",
        "current_price": "55.0",
        "protocol": signal_type,
        "advice": advice_map.get(signal_type, "卖出条件触发"),
        "severity": "emergency",
        "sell_ratio": "1.0",
        "reason": f"e2e demo {signal_type}",
        "position_id": f"e2e-{symbol}",
        "event_id": str(uuid.uuid4()),
        "triggered_at": now,
        "is_revocable": "False",
        "source": "exit-engine",
        "name": name,
    }


def _build_dispatcher(redis_client: aioredis.Redis | None) -> AlertDispatcher:
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
    return AlertDispatcher(
        redis_client,
        AsyncSessionLocal,
        channels,
        deduper,
        sla,
        default_user_id="default",
    )


async def _ensure_group(client: aioredis.Redis) -> None:
    try:
        await client.xgroup_create(STREAM, CONSUMER_GROUP, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def _poll_and_dispatch(
    client: aioredis.Redis,
    dispatcher: AlertDispatcher,
    *,
    block_ms: int = 3000,
) -> dict | None:
    await _ensure_group(client)
    entries = await client.xreadgroup(
        groupname=CONSUMER_GROUP,
        consumername="copilot_step05_e2e",
        streams={STREAM: ">"},
        count=1,
        block=block_ms,
    )
    if not entries:
        return None
    for _stream, messages in entries:
        for msg_id, data in messages:
            event = _parse_stream_fields(data)
            alert = map_event_to_alert("default", STREAM, event)
            if alert is None:
                await client.xack(STREAM, CONSUMER_GROUP, msg_id)
                return {"skipped": True, "reason": "no alert mapping", "msg_id": msg_id}
            result = await dispatcher.dispatch(alert)
            await client.xack(STREAM, CONSUMER_GROUP, msg_id)
            return {
                "msg_id": msg_id,
                "alert_id": alert.alert_id,
                "level": alert.level.value,
                "alert_type": alert.alert_type.value,
                "channels": result,
            }
    return None


async def run_e2e(*, symbol: str, name: str, signal_type: str, skip_xadd: bool) -> int:
    await init_db()
    url = _redis_url()
    client = aioredis.from_url(url, decode_responses=True)
    try:
        try:
            await client.ping()
        except Exception as exc:
            print(f"❌ Redis 不可达 {url}: {exc}", file=sys.stderr)
            return 1

        dispatcher = _build_dispatcher(client)

        if not skip_xadd:
            payload = _demo_payload(symbol=symbol, name=name, signal_type=signal_type)
            msg_id = await client.xadd(STREAM, payload)
            print(f"▶ XADD {STREAM} msg_id={msg_id} symbol={symbol} signal={signal_type}")

        outcome = await _poll_and_dispatch(client, dispatcher)
        if outcome is None:
            print("❌ 未消费到 sell_signal 消息", file=sys.stderr)
            return 1

        print(f"✅ 消费并派发: {outcome}")
        email = outcome.get("channels", {}).get("email", {})
        if email.get("ok"):
            print(f"✅ 邮件已发送 → {settings.smtp_to}")
            return 0
        if "[STUB]" in str(email.get("reason", "")):
            print(f"⚠️  邮件 STUB（缺 SMTP 凭证）: {email.get('reason')}", file=sys.stderr)
            return 1
        print(f"❌ 邮件发送失败: {email}", file=sys.stderr)
        return 1
    finally:
        await client.aclose()


async def run_direct(*, symbol: str, name: str, signal_type: str) -> int:
    """无 Redis 时：map + dispatch 直连（单测/降级）。"""
    await init_db()
    dispatcher = _build_dispatcher(None)
    event = _demo_payload(symbol=symbol, name=name, signal_type=signal_type)
    alert = map_event_to_alert("default", STREAM, event)
    if alert is None:
        print("❌ map_event_to_alert 返回 None", file=sys.stderr)
        return 1
    result = await dispatcher.dispatch(alert)
    print(f"✅ 直连派发 alert_id={alert.alert_id} channels={result}")
    email = result.get("email", {})
    return 0 if email.get("ok") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="D0 step_05 sell_signal → 邮件 e2e")
    parser.add_argument("--symbol", default="601138")
    parser.add_argument("--name", default="工业富联")
    parser.add_argument("--signal-type", default="stop_loss", choices=[
        "stop_loss", "take_profit", "thesis_invalid", "rebalance", "financial_window"
    ])
    parser.add_argument("--skip-xadd", action="store_true", help="仅消费已有消息")
    parser.add_argument("--direct", action="store_true", help="跳过 Redis，直连 dispatch")
    args = parser.parse_args()

    if args.direct:
        return asyncio.run(run_direct(symbol=args.symbol, name=args.name, signal_type=args.signal_type))
    return asyncio.run(
        run_e2e(symbol=args.symbol, name=args.name, signal_type=args.signal_type, skip_xadd=args.skip_xadd)
    )


if __name__ == "__main__":
    raise SystemExit(main())
