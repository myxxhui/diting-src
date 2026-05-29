"""Teacher 蒸馏器主类。

输入：DistillInput 列表
输出：DistillOutput JSONL 文件 + MinIO 归档 + 批次结果

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_02]
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Sequence

from apps.super_evo.config import settings
from apps.super_evo.storage.minio_client import MinIOClient
from apps.super_evo.teacher.clients.anthropic_client import (
    AnthropicTeacherClient,
    TeacherAPIError,
    TeacherResponse,
)
from apps.super_evo.teacher.prompts import get_prompt
from apps.super_evo.teacher.rate_limiter import RateLimiter
from apps.super_evo.teacher.schemas import (
    DistillBatchResult,
    DistillInput,
    DistillMetadata,
    DistillOutput,
)

logger = logging.getLogger(__name__)

REQUIRED_OUTPUT_KEYS = {"risk_score", "decision", "evidence", "reasoning", "confidence"}
DECISION_VALUES = {"pass", "degrade", "reject"}


class TeacherDistiller:
    """Teacher LLM 蒸馏器。

    主要方法：
    - distill_one: 单条蒸馏（含 Prompt 拼装、API 调用、解析、JSONL 拼装）
    - distill_batch: 批量蒸馏（含并发、限流、JSONL 写盘、MinIO 归档）
    """

    def __init__(
        self,
        client: AnthropicTeacherClient | None = None,
        rate_limiter: RateLimiter | None = None,
        minio: MinIOClient | None = None,
        concurrency: int = 4,
        per_minute: int = 30,
        burst: int = 5,
    ) -> None:
        self.client = client or AnthropicTeacherClient()
        self.rate_limiter = rate_limiter or RateLimiter(per_minute=per_minute, burst=burst)
        self.minio = minio
        self.concurrency = concurrency

    async def distill_one(self, item: DistillInput, batch_id: str | None = None) -> DistillOutput:
        prompt = get_prompt(item.task_type)
        messages = prompt.to_messages(item.raw_data, item.context)

        await self.rate_limiter.acquire()
        response = await self.client.chat(messages)
        parsed = self._parse_response(response)

        meta = DistillMetadata(
            task_type=item.task_type,
            teacher_model=response.model,
            distill_timestamp=datetime.utcnow().isoformat() + "Z",
            verified=False,
            verifier=None,
            sample_id=item.sample_id,
            batch_id=batch_id,
        )

        return DistillOutput(
            instruction=prompt.instruction,
            input=prompt.format_input_summary(item.raw_data),
            output=json.dumps(parsed, ensure_ascii=False),
            metadata=meta,
        )

    async def distill_batch(
        self,
        items: Sequence[DistillInput],
        task_type: str,
        output_dir: str | Path | None = None,
        upload_minio: bool = True,
    ) -> DistillBatchResult:
        if not items:
            raise ValueError("items 不能为空")

        batch_id = f"{task_type}_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"
        started_at = datetime.utcnow()

        output_dir = Path(output_dir) if output_dir else settings.storage_root / "distilled" / task_type
        output_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = output_dir / f"{batch_id}.jsonl"

        sem = asyncio.Semaphore(self.concurrency)
        errors: list[str] = []

        async def _run(it: DistillInput) -> DistillOutput | None:
            async with sem:
                try:
                    return await self.distill_one(it, batch_id=batch_id)
                except Exception as exc:
                    errors.append(f"sample={it.sample_id or '?'}: {type(exc).__name__}: {exc}")
                    logger.warning("distill failed: %s", exc)
                    return None

        tasks = [_run(it) for it in items]
        results = await asyncio.gather(*tasks)

        successes = [r for r in results if r is not None]
        with jsonl_path.open("w", encoding="utf-8") as f:
            for r in successes:
                f.write(r.to_jsonl_line() + "\n")

        minio_uri = None
        if upload_minio and self.minio is not None and successes:
            date_str = started_at.strftime("%Y%m%d")
            key = f"distilled/{task_type}/{date_str}/{batch_id}.jsonl"
            minio_uri = self.minio.upload_file(jsonl_path, key)

        finished_at = datetime.utcnow()
        return DistillBatchResult(
            batch_id=batch_id,
            task_type=task_type,  # type: ignore[arg-type]
            num_total=len(items),
            num_success=len(successes),
            num_failed=len(items) - len(successes),
            jsonl_path=str(jsonl_path),
            minio_uri=minio_uri,
            started_at=started_at,
            finished_at=finished_at,
            errors=errors[:50],
        )

    def _parse_response(self, response: TeacherResponse) -> dict:
        text = response.text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                raise TeacherAPIError(f"无法从响应中提取 JSON: {text[:200]}")
            data = json.loads(match.group())

        missing = REQUIRED_OUTPUT_KEYS - set(data.keys())
        if missing:
            raise TeacherAPIError(f"响应缺少必填字段: {missing}")

        if data["decision"] not in DECISION_VALUES:
            raise TeacherAPIError(
                f"decision={data['decision']!r} 不在允许集合 {DECISION_VALUES}"
            )

        try:
            float(data["risk_score"])
            float(data["confidence"])
        except (TypeError, ValueError) as exc:
            raise TeacherAPIError(f"risk_score/confidence 非数值: {exc}") from exc

        if not isinstance(data["evidence"], list):
            raise TeacherAPIError("evidence 必须为列表")

        return data
