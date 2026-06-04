"""akshare 调用薄封装（硬超时 · 重试 · no-mock）。

[Ref: 27_ §2 · P3]
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
_AK_TIMEOUT = float(os.environ.get("RADAR_T0_AKSHARE_TIMEOUT_SEC", "30"))
_AK_RETRY = int(os.environ.get("RADAR_T0_AKSHARE_RETRY", "2"))


def ak_call(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T | None:
    last_exc: Exception | None = None
    for attempt in range(_AK_RETRY + 1):
        if attempt:
            time.sleep(min(1.5 * attempt, 5.0))
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(fn, *args, **kwargs)
            try:
                return fut.result(timeout=_AK_TIMEOUT)
            except FuturesTimeout:
                logger.warning(
                    "akshare 超时 %ss (%s/%s): %s",
                    _AK_TIMEOUT,
                    attempt + 1,
                    _AK_RETRY + 1,
                    getattr(fn, "__name__", fn),
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "akshare 失败 (%s/%s) %s: %s",
                    attempt + 1,
                    _AK_RETRY + 1,
                    getattr(fn, "__name__", fn),
                    exc,
                )
    if last_exc is not None:
        logger.warning("akshare 放弃 %s: %s", getattr(fn, "__name__", fn), last_exc)
    return None
