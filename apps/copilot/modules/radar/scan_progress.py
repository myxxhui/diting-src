"""深度扫描任务进度（Redis / 内存 · 供 HTMX 轮询）。

[Ref: 24_行情解析工作台 · 启动扫描异步化]
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

_TTL_SEC = 1800
_MEMORY: dict[int, dict[str, Any]] = {}

def scan_step_order() -> list[tuple[str, str, int]]:
    """与 run_radar_pipeline 一致；T1 文案随 RADAR_T1_MODE / DEEPSEEK_API_KEY 变化。"""
    from apps.copilot.modules.radar.model_router import t1_step_label

    return [
        ("resolve", "解析标的代码", 5),
        ("t0", "T0 采集行情与公司资料", 20),
        ("t1", t1_step_label(), 45),
        ("t2", "T2 Opus 维度模板推理", 75),
        ("persist", "写入缓存与候选库", 92),
        ("done", "分析完成", 100),
    ]


# 向后兼容
SCAN_STEP_ORDER: list[tuple[str, str, int]] = scan_step_order()


def _redis_key(scan_id: int) -> str:
    return f"radar:scan:{scan_id}"


def _save(redis_client: Any, scan_id: int, payload: dict[str, Any]) -> None:
    payload["updated_at"] = time.time()
    if redis_client is not None:
        try:
            redis_client.setex(
                _redis_key(scan_id),
                _TTL_SEC,
                json.dumps(payload, ensure_ascii=False),
            )
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("scan progress redis write failed: %s", exc)
    _MEMORY[scan_id] = payload


def load(redis_client: Any, scan_id: int) -> dict[str, Any] | None:
    if redis_client is not None:
        try:
            raw = redis_client.get(_redis_key(scan_id))
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("scan progress redis read failed: %s", exc)
    return _MEMORY.get(scan_id)


def init_scan(
    redis_client: Any,
    scan_id: int,
    *,
    symbol: str = "",
    name: str = "",
) -> dict[str, Any]:
    payload = {
        "scan_id": scan_id,
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
    _save(redis_client, scan_id, payload)
    return payload


def update_scan(
    redis_client: Any,
    scan_id: int,
    *,
    step: str,
    step_label: str | None = None,
    pct: int | None = None,
    detail: str = "",
    append_done: bool = True,
) -> dict[str, Any]:
    cur = load(redis_client, scan_id) or init_scan(redis_client, scan_id)
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
        for sid, label, bound in scan_step_order():
            if sid == step:
                cur["pct"] = bound
                cur["step_label"] = label
                break
    if detail:
        cur["detail"] = detail[:300]
    cur["status"] = "running"
    _save(redis_client, scan_id, cur)
    return cur


def finish_scan(
    redis_client: Any,
    scan_id: int,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cur = load(redis_client, scan_id) or {}
    cur.update(
        {
            "status": "done",
            "step": "done",
            "step_label": "分析完成",
            "pct": 100,
            "result": result or {},
            "error": None,
        }
    )
    _save(redis_client, scan_id, cur)
    return cur


def fail_scan(
    redis_client: Any,
    scan_id: int,
    error: str,
    *,
    step: str = "error",
) -> dict[str, Any]:
    cur = load(redis_client, scan_id) or {}
    cur.update(
        {
            "status": "error",
            "step": step,
            "step_label": "分析失败",
            "error": error[:500],
            "pct": cur.get("pct", 0),
        }
    )
    _save(redis_client, scan_id, cur)
    return cur


def make_progress_callback(
    redis_client: Any,
    scan_id: int,
) -> Callable[[str, str, int | None, str], None]:
    def _cb(step: str, label: str, pct: int | None = None, detail: str = "") -> None:
        update_scan(
            redis_client,
            scan_id,
            step=step,
            step_label=label,
            pct=pct,
            detail=detail,
        )

    return _cb
