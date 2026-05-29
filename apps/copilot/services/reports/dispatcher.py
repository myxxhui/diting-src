"""经 AlertDispatcher 推送日报 / 周报（邮件可用 HTML 覆盖）。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from apps.copilot.services.alerts.dispatcher import AlertDispatcher
from apps.copilot.services.alerts.models import Alert, AlertLevel, AlertType


@dataclass
class ReportPush:
    title: str
    html_body: str
    markdown_body: str
    user_id: str
    is_demo: bool
    digest_symbol: str


class ReportDispatcher:
    def __init__(self, alert_dispatcher: AlertDispatcher) -> None:
        self.alert_dispatcher = alert_dispatcher

    async def push(self, push: ReportPush) -> dict[str, Any]:
        sym = push.digest_symbol[:16] if len(push.digest_symbol) > 16 else push.digest_symbol
        msg = push.markdown_body
        if len(msg) > 1800:
            msg = msg[:1800] + "…"
        name = push.title[:64] if len(push.title) > 64 else push.title
        alert = Alert(
            alert_id=str(uuid.uuid4()),
            user_id=push.user_id,
            level=AlertLevel.ORANGE,
            alert_type=AlertType.DEGRADE,
            symbol=sym,
            name=name,
            message=msg,
            payload={"html_override": push.html_body, "email_subject": push.title},
            created_at=datetime.now(timezone.utc),
        )
        res = await self.alert_dispatcher.dispatch(alert, force=True)
        if res.get("dedup") is True or res.get("circuit_open") is True:
            any_ok = False
        else:
            any_ok = any(
                isinstance(v, dict) and bool(v.get("ok")) for v in res.values()
            )
        return {
            "raw": res,
            "any_ok": any_ok,
            "sent_at": datetime.now(timezone.utc) if any_ok else None,
        }
