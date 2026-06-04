"""T0 采集任务进度（Redis / 内存 · 供 HTMX 轮询）。

[Ref: 24_ §10 · 波次四采集数据]
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable

logger = logging.getLogger(__name__)

_TTL_SEC = 600
_MEMORY: dict[str, dict[str, Any]] = {}

# step_id, 中文标签, 进度占比上界(0-100)
COLLECT_STEP_ORDER: list[tuple[str, str, int]] = [
    ("resolve", "解析标的代码", 8),
    ("quote", "行情 K 线（腾讯/新浪链）", 28),
    ("profile", "公司资料", 45),
    ("financials", "财务摘要", 62),
    ("valuation", "估值分位", 78),
    ("t1", "T1 事实矩阵压缩", 88),
    ("persist", "写入文件缓存与数据库", 96),
    ("done", "完成", 100),
]


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]


def _redis_key(job_id: str) -> str:
    return f"radar:collect:{job_id}"


def _save(redis_client: Any, job_id: str, payload: dict[str, Any]) -> None:
    payload["updated_at"] = time.time()
    if redis_client is not None:
        try:
            redis_client.setex(
                _redis_key(job_id),
                _TTL_SEC,
                json.dumps(payload, ensure_ascii=False),
            )
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("collect progress redis write failed: %s", exc)
    _MEMORY[job_id] = payload


def load(redis_client: Any, job_id: str) -> dict[str, Any] | None:
    if redis_client is not None:
        try:
            raw = redis_client.get(_redis_key(job_id))
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("collect progress redis read failed: %s", exc)
    return _MEMORY.get(job_id)


def init_job(
    redis_client: Any,
    job_id: str,
    *,
    symbol: str = "",
    name: str = "",
) -> dict[str, Any]:
    payload = {
        "job_id": job_id,
        "status": "running",
        "symbol": symbol,
        "name": name,
        "step": "resolve",
        "step_label": "准备中…",
        "pct": 0,
        "detail": "",
        "steps_done": [],
        "error": None,
        "result": None,
    }
    _save(redis_client, job_id, payload)
    return payload


def update_job(
    redis_client: Any,
    job_id: str,
    *,
    step: str,
    step_label: str | None = None,
    pct: int | None = None,
    detail: str = "",
    append_done: bool = True,
) -> dict[str, Any]:
    cur = load(redis_client, job_id) or init_job(redis_client, job_id)
    prev_step = cur.get("step")
    if append_done and prev_step and prev_step != step:
        done = cur.setdefault("steps_done", [])
        if prev_step not in done and prev_step not in ("error", "done"):
            done.append(prev_step)
    cur["step"] = step
    if step_label is not None:
        cur["step_label"] = step_label
    if pct is not None:
        cur["pct"] = min(100, max(0, int(pct)))
    elif append_done:
        for sid, label, bound in COLLECT_STEP_ORDER:
            if sid == step:
                cur["pct"] = bound
                cur["step_label"] = label
                break
    if detail:
        cur["detail"] = detail[:300]
    cur["status"] = "running"
    _save(redis_client, job_id, cur)
    return cur


def finish_job(
    redis_client: Any,
    job_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    cur = load(redis_client, job_id) or {}
    cur.update(
        {
            "status": "done",
            "step": "done",
            "step_label": "采集完成",
            "pct": 100,
            "result": result,
            "error": None,
        }
    )
    _save(redis_client, job_id, cur)
    return cur


def fail_job(
    redis_client: Any,
    job_id: str,
    error: str,
    *,
    step: str = "error",
) -> dict[str, Any]:
    cur = load(redis_client, job_id) or {}
    cur.update(
        {
            "status": "error",
            "step": step,
            "step_label": "采集失败",
            "error": error[:500],
            "pct": cur.get("pct", 0),
        }
    )
    _save(redis_client, job_id, cur)
    return cur


def make_progress_callback(
    redis_client: Any,
    job_id: str,
) -> Callable[[str, str, int | None, str], None]:
    def _cb(step: str, label: str, pct: int | None = None, detail: str = "") -> None:
        update_job(
            redis_client,
            job_id,
            step=step,
            step_label=label,
            pct=pct,
            detail=detail,
        )

    return _cb
