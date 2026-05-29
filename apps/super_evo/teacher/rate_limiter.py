"""Teacher API 令牌桶限流。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_02]
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class TokenBucket:
    """异步令牌桶（RPS 限制）。

    rate: 每秒补充的令牌数（= 允许的稳态 RPS）
    capacity: 桶容量（= 允许的突发请求数）
    """

    rate: float
    capacity: float
    tokens: float = field(init=False)
    last_refill: float = field(init=False)
    _lock: asyncio.Lock = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = self.capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    async def acquire(self, n: float = 1.0) -> None:
        if n > self.capacity:
            raise ValueError(f"requested {n} > capacity {self.capacity}")
        while True:
            async with self._lock:
                self._refill()
                if self.tokens >= n:
                    self.tokens -= n
                    return
                need = (n - self.tokens) / self.rate
            await asyncio.sleep(need)


class RateLimiter:
    """Teacher API 限流器。

    - per_minute: 每分钟最多请求数（默认 30）
    - burst: 允许的突发（默认 5）
    """

    def __init__(self, per_minute: int = 30, burst: int = 5) -> None:
        self.per_minute = per_minute
        self.burst = burst
        self._bucket = TokenBucket(rate=per_minute / 60.0, capacity=float(burst))

    async def acquire(self) -> None:
        await self._bucket.acquire(1.0)
