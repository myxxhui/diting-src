"""启动期 no-mock-policy 守卫（[Ref: 14_六维度启动期统一节奏表 §8]）."""
from __future__ import annotations

import os
import sys


def in_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def reject_business_mock(env_flag: str, *, context: str = "") -> None:
    """业务路径检测到 mock 开关时 hard fail；tests/ 内 pytest 仍可用 monkeypatch。"""
    val = os.environ.get(env_flag, "").strip().lower()
    if val not in ("1", "true", "yes"):
        return
    if in_pytest():
        return
    ctx = f" ({context})" if context else ""
    print(
        f"❌ {env_flag}=1 已禁用{ctx}。"
        " no-mock-policy：禁止伪造数据入库/进训练集；"
        "请配置真实凭证或仅在 tests/ 内使用 fixture。",
        file=sys.stderr,
    )
    raise SystemExit(2)
