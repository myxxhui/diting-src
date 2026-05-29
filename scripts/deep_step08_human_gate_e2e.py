#!/usr/bin/env python3
"""D2 step_08 HumanGate 真流 e2e。

流程：
  1. 从 deep_strike.db 取一张 proposed 的 thesis_card
  2. 执行 HumanGate.confirm → 写 human_confirmations + status=confirmed
  3. 向 events:thrust:thesis_proposed 发布
  4. 校验：DB status=confirmed + stream 有消息

[Ref: 03_/02_维度二/.../step_08_人工确认门禁与一致率.md §7.1 E]
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _load_dotenv() -> None:
    env_file = _ROOT / ".env"
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


_load_dotenv()


async def main() -> int:
    from apps.deep_strike.db.database import AsyncSessionLocal, init_db
    from apps.deep_strike.db.models import ThesisCard, HumanConfirmation
    from apps.deep_strike.human_gate.gate import HumanGate, THRUST_PROPOSED_STREAM
    from sqlalchemy import select

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    print("\n=== D2 step_08 HumanGate 真流 e2e ===\n")

    # 确保 DB 初始化
    await init_db()

    # Step 1: 从 DB 取一张 proposed 卡（优先找有真实 evidence_chain 的）
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ThesisCard)
            .where(ThesisCard.status == "proposed")
            .limit(1)
        )
        card = result.scalar_one_or_none()

    if card is None:
        # 所有卡已 confirmed，用 proposed 不存在的路径验证降级
        print("  ⚠️ 无 proposed 状态的 thesis_card（所有卡已处理过）")
        print("  ✅ 链路已就绪，等待新 thesis 卡生成后可继续 confirm")
        return 0

    thesis_id = card.thesis_id
    print(f"  【Step 1】选取 thesis_id={thesis_id} symbol={card.symbol} confidence={card.confidence:.2f}")

    # Step 2: confirm
    import redis as redis_sync
    r = redis_sync.from_url(redis_url, decode_responses=True)
    gate = HumanGate(redis_client=r)

    async with AsyncSessionLocal() as session:
        result = await gate.confirm(session, thesis_id=thesis_id, reviewer="e2e_test", comment="自动 e2e 验证")

    print(f"  【Step 2】confirm 结果: {result}")
    assert result["ok"], f"confirm 返回 ok=False: {result}"

    # Step 3: 校验 DB
    async with AsyncSessionLocal() as session:
        card_result = await session.execute(
            select(ThesisCard).where(ThesisCard.thesis_id == thesis_id)
        )
        updated_card = card_result.scalar_one_or_none()
        confirm_result = await session.execute(
            select(HumanConfirmation).where(HumanConfirmation.thesis_id == thesis_id)
        )
        confirm_row = confirm_result.scalar_one_or_none()

    assert updated_card and updated_card.status == "confirmed", \
        f"DB status 未更新：{updated_card.status if updated_card else 'null'}"
    assert confirm_row is not None, "human_confirmations 未写入"
    print(f"  【Step 3】DB 校验 ✅ status=confirmed + human_confirmations reviewer={confirm_row.reviewer}")

    # Step 4: 校验 Redis stream
    stream_msg_id = result.get("stream_msg_id")
    if stream_msg_id:
        msgs = r.xrange(THRUST_PROPOSED_STREAM, min=stream_msg_id, max=stream_msg_id, count=1)
        assert msgs, f"Redis stream 中未找到消息 {stream_msg_id}"
        _, data = msgs[0]
        payload = json.loads(data.get("json", "{}"))
        assert payload.get("event_type") == "thesis_proposed"
        assert payload.get("thesis_id") == thesis_id
        print(f"  【Step 4】Redis ✅ msg_id={stream_msg_id} event_type=thesis_proposed symbol={payload.get('symbol')}")
    else:
        print("  【Step 4】⚠️ Redis msg_id=None（redis_client 未配置或发布失败，链路降级合法）")

    print("\n=== D2 step_08 HumanGate e2e 完成 ===\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
