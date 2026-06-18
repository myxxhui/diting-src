"""Tushare Pro 薄封装 · Z0 段 A 优先数据源。

[Ref: 34_ §3 · smart_money_flow.tushare_token]
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


def tushare_token() -> str | None:
    tok = (os.environ.get("TUSHARE_TOKEN") or os.environ.get("TUSHARE_PRO_TOKEN") or "").strip()
    return tok or None


def tushare_available() -> bool:
    return tushare_token() is not None


@lru_cache(maxsize=1)
def pro_api():
    import tushare as ts  # type: ignore

    token = tushare_token()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    ts.set_token(token)
    return ts.pro_api()


def ts_call(fn_name: str, **kwargs: Any) -> Any:
    """调用 pro 接口 · 失败抛异常供上层 fallback。"""
    fn = getattr(pro_api(), fn_name)
    return fn(**kwargs)
