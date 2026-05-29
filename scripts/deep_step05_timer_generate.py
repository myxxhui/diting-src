#!/usr/bin/env python3
"""对 thesis 卡生成 The Timer timer_signal（Opus 真流 · force_route=remote）。

[Ref: 03_/02_维度二/.../step_05 §7.2 deep-step05-timer-generate]
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

from apps.deep_strike.config import settings
from apps.deep_strike.db.database import AsyncSessionLocal, init_db
from apps.deep_strike.db.models import ThesisCard, TimerSignalRecord
from apps.deep_strike.events.publisher import get_publisher
from apps.deep_strike.lighthouse.schemas import TimerInput
from apps.deep_strike.lighthouse.timer import TheTimer


def _load_dotenv() -> None:
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)
    except ImportError:
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())


async def _run(limit: int, *, force: bool) -> int:
    _load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        print("❌ ANTHROPIC_API_KEY 未配置，无法执行 The Timer Opus 真流", file=sys.stderr)
        return 1

    from apps.common.ai_dispatcher import AIDispatcher

    AIDispatcher._instance = None
    dispatcher = AIDispatcher.default()
    timer = TheTimer(dispatcher=dispatcher)

    await init_db()
    done = 0
    remote_ok = 0
    redis_msgs: list[str] = []

    async with AsyncSessionLocal() as session:
        rows = (
            await session.scalars(
                select(ThesisCard).order_by(ThesisCard.id.desc()).limit(limit * 3)
            )
        ).all()
        if not rows:
            print("⚠️ 无 thesis 卡；请先 make deep-step05-generate-all", file=sys.stderr)
            return 1

        pub = get_publisher(settings.redis_url)
        targets = [r for r in rows if force or not r.timer_signal][:limit]

        for row in targets:
            timer_input = TimerInput(
                thesis_card_id=row.thesis_id,
                symbol=row.symbol,
                current_date=date.today(),
                scan_hit_signals=[row.playbook_id, row.action],
            )
            output = timer.call(timer_input, force_route="remote")
            if output.incubation.confidence <= 0.31:
                output = timer.call(timer_input, force_route="remote")
            ts = output.model_dump(mode="json")
            route = (output.metadata.route if output.metadata else "mock")
            model = output.metadata.model_name if output.metadata else "?"

            if route != "remote":
                print(f"❌ {row.symbol}: 非 Opus 真流 route={route}", file=sys.stderr)
                return 1

            remote_ok += 1
            row.timer_signal = ts
            session.add(
                TimerSignalRecord(
                    thesis_card_id=row.thesis_id,
                    symbol=row.symbol,
                    timer_signal=ts,
                    generated_by={"route": route, "model": model},
                    raw_llm_response=None,
                )
            )
            msg_ids = pub.publish_timer_phases_from_card(
                thesis_card_id=row.thesis_id,
                symbol=row.symbol,
                timer_signal=ts,
            )
            redis_msgs.extend([m for m in msg_ids if m])
            done += 1
            print(
                f"✅ {row.symbol} Opus timer · route={route} model={model} "
                f"phases=3 anchors={len(output.cycle_anchors)} redis={msg_ids}"
            )

        await session.commit()

    print(f"✅ timer-generate Opus 真流: {remote_ok}/{done} remote · redis_xadd={len(redis_msgs)}")
    return 0 if done > 0 and remote_ok == done else 1


def main() -> int:
    limit = int(os.environ.get("TIMER_GENERATE_LIMIT", "3"))
    force = os.environ.get("TIMER_FORCE", "0") == "1"
    return asyncio.run(_run(limit, force=force))


if __name__ == "__main__":
    raise SystemExit(main())
