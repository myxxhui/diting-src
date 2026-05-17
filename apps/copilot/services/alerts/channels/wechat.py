"""企业微信群机器人通道。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_05]
"""
from __future__ import annotations

import httpx

from apps.copilot.services.alerts.channels.base import BaseChannel, ChannelResult
from apps.copilot.services.alerts.models import Alert, AlertLevel


class WechatChannel(BaseChannel):
    name = "wechat"

    def __init__(self, webhook_url: str | None, timeout: float = 5.0):
        self._url = webhook_url
        self._timeout = timeout

    async def send(self, alert: Alert) -> ChannelResult:
        if not self._url:
            return ChannelResult(channel=self.name, ok=False, reason="[STUB] missing_webhook")

        emoji = "🔴" if alert.level == AlertLevel.RED else "🟠"
        content = (
            f"## {emoji} {alert.level.value.upper()} 告警\n"
            f"> **{alert.symbol}** {alert.name}\n\n"
            f"**类型**: `{alert.alert_type.value}`\n\n"
            f"**详情**: {alert.message}\n\n"
            f"**时间**: {alert.created_at.isoformat()}"
        )
        payload = {"msgtype": "markdown", "markdown": {"content": content}}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._url, json=payload)
            if resp.status_code == 200 and resp.json().get("errcode", 0) == 0:
                return ChannelResult(channel=self.name, ok=True, sent_at=self.now())
            return ChannelResult(
                channel=self.name,
                ok=False,
                reason=f"status={resp.status_code} body={resp.text[:200]}",
            )
        except Exception as e:  # noqa: BLE001
            return ChannelResult(channel=self.name, ok=False, reason=f"exception={e!r}")
