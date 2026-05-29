"""SMTP 邮件通道。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_05]
"""
from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib

from apps.copilot.services.alerts.channels.base import BaseChannel, ChannelResult
from apps.copilot.services.alerts.models import Alert, AlertLevel


class EmailChannel(BaseChannel):
    name = "email"

    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        sender: str,
        recipient: str | None,
        use_ssl: bool = False,
        timeout: float = 10.0,
    ):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender
        self._recipient = recipient
        self._use_ssl = use_ssl
        self._timeout = timeout

    async def send(self, alert: Alert) -> ChannelResult:
        if not self._username or not self._password or not self._recipient:
            return ChannelResult(channel=self.name, ok=False, reason="[STUB] missing_smtp_credentials")

        msg = EmailMessage()
        emoji = "🔴" if alert.level == AlertLevel.RED else "🟠"
        payload = alert.payload or {}
        subject_override = payload.get("email_subject")
        if subject_override:
            msg["Subject"] = str(subject_override)
        else:
            msg["Subject"] = (
                f"[{emoji} {alert.level.value.upper()}] {alert.symbol} {alert.name} · "
                f"{alert.alert_type.value}"
            )
        msg["From"] = self._sender
        msg["To"] = self._recipient
        msg.set_content(
            f"{alert.level.value.upper()} 告警\n\n"
            f"标的: {alert.symbol} {alert.name}\n"
            f"类型: {alert.alert_type.value}\n"
            f"详情: {alert.message}\n"
            f"时间: {alert.created_at.isoformat()}\n"
        )
        html_override = payload.get("html_override")
        if html_override:
            msg.add_alternative(html_override, subtype="html")
        else:
            msg.add_alternative(
                f"""<html><body>
<h2>{emoji} {alert.level.value.upper()} 告警</h2>
<p><strong>{alert.symbol}</strong> {alert.name}</p>
<p>类型: <code>{alert.alert_type.value}</code></p>
<p>{alert.message}</p>
<p>时间: {alert.created_at.isoformat()}</p>
</body></html>""",
            subtype="html",
        )

        try:
            await aiosmtplib.send(
                msg,
                hostname=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                use_tls=self._use_ssl,
                start_tls=not self._use_ssl,
                timeout=self._timeout,
            )
            return ChannelResult(channel=self.name, ok=True, sent_at=self.now())
        except Exception as e:  # noqa: BLE001
            return ChannelResult(channel=self.name, ok=False, reason=f"exception={e!r}")
