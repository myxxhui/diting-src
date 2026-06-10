"""T2 持仓分析异步任务进度（Redis · HTMX 轮询）。

长 Opus 调用（3～5 分钟）不得占用浏览器↔Copilot 同步 HTTP；后台任务 + 轮询与雷达深度扫描同模式。

[Ref: 28_ §5 · 24_ 启动扫描异步化]
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable

logger = logging.getLogger(__name__)

_TTL_SEC = 3600
_MEMORY: dict[str, dict[str, Any]] = {}


def new_job_id() -> str:
    return uuid.uuid4().hex[:16]


def _redis_key(job_id: str) -> str:
    return f"executing:t2:job:{job_id}"


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
            logger.warning("t2 job progress redis write failed: %s", exc)
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
            logger.warning("t2 job progress redis read failed: %s", exc)
    return _MEMORY.get(job_id)


def init_job(
    redis_client: Any,
    job_id: str,
    *,
    session_id: str,
    symbols: list[str],
) -> dict[str, Any]:
    state = {
        "job_id": job_id,
        "session_id": session_id,
        "symbols": list(symbols or []),
        "status": "running",
        "step": "queued",
        "step_label": "任务已提交…",
        "pct": 5,
        "started_at": time.time(),
        "error": None,
        "result": None,
    }
    _save(redis_client, job_id, state)
    if redis_client is not None and session_id:
        try:
            redis_client.setex(
                f"executing:t2:active:{session_id}",
                _TTL_SEC,
                job_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("t2 active job index write failed: %s", exc)
    return state


def clear_active_job(redis_client: Any, session_id: str) -> None:
    if redis_client is None or not session_id:
        return
    try:
        redis_client.delete(f"executing:t2:active:{session_id}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("t2 active job index clear failed: %s", exc)


def active_job_id(redis_client: Any, session_id: str) -> str | None:
    if redis_client is None or not session_id:
        return None
    try:
        raw = redis_client.get(f"executing:t2:active:{session_id}")
        if raw:
            return raw.decode() if isinstance(raw, bytes) else str(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("t2 active job index read failed: %s", exc)
    return None


def update_job(
    redis_client: Any,
    job_id: str,
    *,
    step: str,
    step_label: str,
    pct: int,
) -> None:
    state = load(redis_client, job_id) or {"job_id": job_id}
    state.update(
        {
            "status": "running",
            "step": step,
            "step_label": step_label,
            "pct": min(99, max(0, int(pct))),
        }
    )
    _save(redis_client, job_id, state)


def finish_job(redis_client: Any, job_id: str, result: dict[str, Any]) -> None:
    state = load(redis_client, job_id) or {"job_id": job_id}
    session_id = str(state.get("session_id") or result.get("session_id") or "")
    state.update(
        {
            "status": "done",
            "step": "done",
            "step_label": "分析完成",
            "pct": 100,
            "result": result,
            "error": None,
        }
    )
    _save(redis_client, job_id, state)
    clear_active_job(redis_client, session_id)


def fail_job(redis_client: Any, job_id: str, error: str) -> None:
    state = load(redis_client, job_id) or {"job_id": job_id}
    session_id = str(state.get("session_id") or "")
    state.update(
        {
            "status": "error",
            "step": "error",
            "step_label": "分析失败",
            "pct": 100,
            "error": (error or "")[:500],
            "result": None,
        }
    )
    _save(redis_client, job_id, state)
    clear_active_job(redis_client, session_id)


def make_progress_callback(
    redis_client: Any, job_id: str
) -> Callable[[str, int, str], None]:
    def _cb(step: str, pct: int, label: str) -> None:
        update_job(redis_client, job_id, step=step, step_label=label, pct=pct)

    return _cb
