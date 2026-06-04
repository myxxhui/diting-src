"""国内行情/代码表 HTTP：防御性绕过进程级代理（正常应仅 ANTHROPIC_HTTPS_PROXY，不设 HTTPS_PROXY）。

[Ref: 26_行情雷达与AI模型工作流 · T0/标的索引]
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
)


@contextmanager
def without_outbound_proxy() -> Iterator[None]:
    """临时移除进程代理环境变量（仅包裹国内数据源调用）。"""
    saved = {k: os.environ.pop(k) for k in _PROXY_ENV_KEYS if k in os.environ}
    try:
        yield
    finally:
        for k, v in saved.items():
            os.environ[k] = v
