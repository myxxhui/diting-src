"""Telegram Bot 通道。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_05]
"""
from __future__ import annotations

import httpx

from apps.copilot.services.alerts.channels.base import BaseChannel, ChannelResult
from apps.copilot.services.alerts.models import Alert, AlertLevel


class TelegramChannel(BaseChannel):
    name = "telegram"

    def __init__(self, bot_token: str | None, chat_id: str | None, timeout: float = 5.0):
        self._token = bot_token
        self._chat_id = chat_id
        self._timeout = timeout

    async def send(self, alert: Alert) -> ChannelResult:
        if not self._token or not self._chat_id:
            return ChannelResult(channel=self.name, ok=False, reason="[STUB] missing_token_or_chat")

        emoji = "🔴" if alert.level == AlertLevel.RED else "🟠"
        text = (
            f"{emoji} *{alert.level.value.upper()} 告警*\n\n"
            f"📈 `{alert.symbol}` {alert.name}\n"
            f"📋 类型: `{alert.alert_type.value}`\n"
            f"💬 {alert.message}\n"
            f"⏰ {alert.created_at.isoformat()}"
        )
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        body = {"chat_id": self._chat_id, "text": text, "parse_mode": "Markdown"}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=body)
            if resp.status_code == 200 and resp.json().get("ok") is True:
                return ChannelResult(channel=self.name, ok=True, sent_at=self.now())
            return ChannelResult(
                channel=self.name,
                ok=False,
                reason=f"status={resp.status_code} body={resp.text[:200]}",
            )
        except Exception as e:  # noqa: BLE001
            return ChannelResult(channel=self.name, ok=False, reason=f"exception={e!r}")
