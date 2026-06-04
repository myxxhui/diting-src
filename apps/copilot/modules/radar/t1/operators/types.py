"""T1 算子统一返回类型。

[Ref: 27_ §3.7]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OpResult:
    domain: str
    key: str
    node: dict[str, Any] | None
    skip_msg: str | None = None


def node(value: Any, tag: str, context: str) -> dict[str, Any]:
    return {"value": value, "tag": tag, "context": context}
