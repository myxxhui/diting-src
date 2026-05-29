"""探针基类.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class ProbeError(Exception):
    """探针运行期错误."""


@dataclass
class ProbeResult:
    probe_type: str
    symbol: str
    data: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    success: bool = True
    error: str = ""
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fetched_at"] = self.fetched_at.isoformat()
        return d


class BaseProbe(ABC):
    """探针抽象基类."""

    probe_type: str = "base"
    timeout_seconds: float = 10.0
    retry_max: int = 2

    @abstractmethod
    async def _fetch_impl(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError

    async def fetch(self, symbol: str) -> ProbeResult:
        start = time.perf_counter()
        last_err = ""
        for attempt in range(self.retry_max + 1):
            try:
                data = await asyncio.wait_for(
                    self._fetch_impl(symbol), timeout=self.timeout_seconds
                )
                elapsed = (time.perf_counter() - start) * 1000
                return ProbeResult(
                    probe_type=self.probe_type,
                    symbol=symbol,
                    data=data,
                    fetched_at=datetime.utcnow(),
                    success=True,
                    elapsed_ms=elapsed,
                )
            except asyncio.TimeoutError:
                last_err = f"timeout after {self.timeout_seconds}s"
                logger.warning("probe=%s symbol=%s attempt=%s timeout", self.probe_type, symbol, attempt)
            except ProbeError as e:
                last_err = str(e)
                logger.warning("probe=%s symbol=%s attempt=%s err=%s", self.probe_type, symbol, attempt, e)
            except Exception as e:
                last_err = f"unexpected:{e}"
                logger.exception("probe=%s symbol=%s attempt=%s unexpected", self.probe_type, symbol, attempt)
        elapsed = (time.perf_counter() - start) * 1000
        await self.on_failure(symbol, last_err)
        return ProbeResult(
            probe_type=self.probe_type,
            symbol=symbol,
            data={},
            fetched_at=datetime.utcnow(),
            success=False,
            error=last_err,
            elapsed_ms=elapsed,
        )

    async def health_check(self) -> bool:
        return True

    async def on_failure(self, symbol: str, error: str) -> None:
        logger.warning("probe=%s symbol=%s on_failure: %s", self.probe_type, symbol, error)
