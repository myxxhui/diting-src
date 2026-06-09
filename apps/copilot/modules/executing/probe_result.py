"""T0/T1 探针统一返回契约。

[Ref: 28_ §9 · probes 架构]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

BlockerCode = Literal["A", "B", "C", "D", "E"]


@dataclass(frozen=True)
class ProbeResult:
    probe_key: str
    ok: bool
    blocker: str | None
    payload: dict[str, Any] | None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe_key": self.probe_key,
            "ok": self.ok,
            "blocker": self.blocker,
            "payload": self.payload,
            "source": self.source,
        }


def ok_result(key: str, payload: dict[str, Any], source: str) -> dict[str, Any]:
    return ProbeResult(key, True, None, payload, source).to_dict()


def block_result(key: str, reason: str) -> dict[str, Any]:
    return ProbeResult(key, False, reason, None, None).to_dict()


def block_typed(key: str, code: BlockerCode, reason: str) -> dict[str, Any]:
    return block_result(key, f"[{code}] {reason}")
