#!/usr/bin/env python3
"""D3 step_09 · 市场阶段分类器批量 + 分布 + 邮件预览.

[Ref: 03_/03_维度三/.../step_09 §7.2]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO = Path(__file__).resolve().parents[1]
load_dotenv(_REPO / ".env", override=False)


async def _prep() -> dict:
    from apps.common.holdings_sot import load_holdings_sot
    from apps.state_watch.db.session import init_db, ping_db

    await init_db()
    sot = load_holdings_sot()
    return {
        "db_ok": await ping_db(),
        "active_count": len(sot.active_symbols()),
        "symbols": sot.active_symbols(),
    }


async def _classify_all(publish: bool = True) -> dict:
    from apps.state_watch.market_phase.orchestrator import classify_all_active

    return await classify_all_active(publish=publish)


async def _distribution() -> dict:
    from apps.state_watch.market_phase.rules_config import load_rules
    from apps.state_watch.market_phase.schemas import MarketPhase
    from sqlalchemy import select

    from apps.state_watch.db.models import HoldingState
    from apps.state_watch.db.session import init_db, session_ctx

    await init_db()
    dist = {p.value: 0 for p in MarketPhase}
    async with session_ctx() as session:
        for h in await session.scalars(select(HoldingState)):
            ph = (h.context or {}).get("market_phase")
            if ph in dist:
                dist[ph] += 1
    labels = load_rules().get("phase_labels_zh") or {}
    return {"distribution": dist, "labels_zh": labels, "total": sum(dist.values())}


async def _email_summary() -> dict:
    """生成 phase 分布摘要并尝试发邮件（需 COPILOT_SMTP_*）."""
    import os

    publish = os.environ.get("MARKET_PHASE_EMAIL_PUBLISH", "0") == "1"
    summary = await _classify_all(publish=publish)
    dist = summary.get("distribution") or {}
    lines = ["【diting】市场阶段快照 · W2 step_09", ""]
    labels = {}
    try:
        from apps.state_watch.market_phase.rules_config import load_rules

        labels = load_rules().get("phase_labels_zh") or {}
    except Exception:
        pass
    for phase, cnt in sorted(dist.items()):
        zh = labels.get(phase, phase)
        lines.append(f"  · {zh} ({phase}): {cnt} 只")
    lines.append("")
    for row in summary.get("results") or []:
        if "error" in row:
            continue
        zh = labels.get(row["market_phase"], row["market_phase"])
        lines.append(
            f"  {row.get('name','')} {row['symbol']} → {zh} "
            f"(conf={row.get('confidence',0):.2f}) tags={row.get('reasoning_tags',[])}"
        )
    body = "\n".join(lines)
    sent = {"ok": False, "reason": "smtp_not_configured"}
    try:
        from apps.copilot.config import settings as copilot_settings
        from apps.copilot.services.alerts.channels.email import EmailChannel
        from apps.copilot.services.alerts.models import Alert, AlertType

        ch = EmailChannel(
            host=copilot_settings.smtp_host,
            port=copilot_settings.smtp_port,
            username=copilot_settings.smtp_username,
            password=copilot_settings.smtp_password,
            sender=copilot_settings.smtp_from,
            recipient=copilot_settings.smtp_to,
            use_ssl=copilot_settings.smtp_use_ssl,
        )
        alert = Alert.new(
            user_id="default",
            alert_type=AlertType.DEGRADE,
            symbol="PORTFOLIO",
            name="全持仓阶段",
            message=body,
            payload={
                "email_subject": "[diting] 市场阶段快照 · 全持仓",
                "html_override": f"<pre>{body}</pre>",
            },
        )
        res = await ch.send(alert)
        sent = {"ok": res.ok, "reason": res.reason}
    except Exception as exc:
        sent = {"ok": False, "reason": repr(exc)}
    return {"summary": summary, "email": sent, "body_preview": body[:500]}


def main() -> int:
    parser = argparse.ArgumentParser(description="D3 step_09 market phase")
    parser.add_argument(
        "command",
        choices=("prep", "classify-all", "distribution", "email-summary", "status"),
    )
    parser.add_argument("--no-publish", action="store_true", help="不推 Redis phase_change")
    args = parser.parse_args()

    if args.command == "prep":
        out = asyncio.run(_prep())
    elif args.command == "classify-all":
        out = asyncio.run(_classify_all(publish=not args.no_publish))
    elif args.command == "distribution":
        out = asyncio.run(_distribution())
    elif args.command == "email-summary":
        out = asyncio.run(_email_summary())
    else:
        prep = asyncio.run(_prep())
        dist = asyncio.run(_distribution())
        out = {**prep, **dist}

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
