"""D5 step02 dry_run 冒烟：单条蒸馏（无 API Key / MinIO）。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_02 §9]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys


async def main() -> None:
    os.environ.setdefault("ANTHROPIC_API_KEY", "")

    from apps.super_evo.teacher.clients.anthropic_client import AnthropicTeacherClient
    from apps.super_evo.teacher.distiller import TeacherDistiller
    from apps.super_evo.teacher.rate_limiter import RateLimiter
    from apps.super_evo.teacher.schemas import DistillInput

    client = AnthropicTeacherClient(api_key="")
    print(f"  teacher_model = {client.model_name}")
    print(f"  dry_run       = {client.dry_run}")

    distiller = TeacherDistiller(
        client=client,
        rate_limiter=RateLimiter(per_minute=60, burst=10),
        minio=None,
    )

    item = DistillInput(
        task_type="financial_fraud",
        raw_data={"symbol": "603556", "text": "测试 dry_run"},
    )
    out = await distiller.distill_one(item)
    data = json.loads(out.output)

    print(f"  decision   = {data['decision']}")
    print(f"  confidence = {data['confidence']}")
    print(f"  model      = {out.metadata.teacher_model}")

    assert data["decision"] in {"pass", "degrade", "reject"}, \
        f"decision 非法: {data['decision']}"
    assert isinstance(data["confidence"], (int, float)), "confidence 非数值"

    print("  ✅ dry_run 冒烟通过")


if __name__ == "__main__":
    asyncio.run(main())
