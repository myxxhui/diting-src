"""行情源断路器（进程级三态机）。

[Ref: 03_/_共享规约/21_行情数据源降级与断路器规约.md §六]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional, TypeVar

from apps.common.market_quote.schemas import SourceHealth

T = TypeVar("T")

FAIL_THRESHOLD = 5
COOL_DOWN_SEC = 60


@dataclass
class _BreakerState:
    status: str = "ok"  # ok | tripped | half_open
    consecutive_failures: int = 0
    last_ok_at: Optional[datetime] = None
    tripped_until: Optional[datetime] = None


class CircuitBreakerRegistry:
    """每源独立断路器。"""

    def __init__(
        self,
        fail_threshold: int = FAIL_THRESHOLD,
        cool_down_sec: int = COOL_DOWN_SEC,
    ) -> None:
        self.fail_threshold = fail_threshold
        self.cool_down_sec = cool_down_sec
        self._states: dict[str, _BreakerState] = {}

    def _state(self, source: str) -> _BreakerState:
        if source not in self._states:
            self._states[source] = _BreakerState()
        return self._states[source]

    def _now(self) -> datetime:
        return datetime.now()

    def can_execute(self, source: str, now: datetime | None = None) -> bool:
        now = now or self._now()
        st = self._state(source)
        if st.status == "ok":
            return True
        if st.status == "tripped":
            if st.tripped_until and now >= st.tripped_until:
                st.status = "half_open"
                return True
            return False
        # half_open: allow one probe
        return True

    def record_success(self, source: str, now: datetime | None = None) -> None:
        now = now or self._now()
        st = self._state(source)
        st.status = "ok"
        st.consecutive_failures = 0
        st.last_ok_at = now
        st.tripped_until = None

    def record_failure(self, source: str, now: datetime | None = None) -> None:
        now = now or self._now()
        st = self._state(source)
        st.consecutive_failures += 1
        if st.status == "half_open":
            st.status = "tripped"
            st.tripped_until = now + timedelta(seconds=self.cool_down_sec)
            return
        if st.consecutive_failures >= self.fail_threshold:
            st.status = "tripped"
            st.tripped_until = now + timedelta(seconds=self.cool_down_sec)

    def call(self, source: str, fn: Callable[[], T], now: datetime | None = None) -> T | None:
        """执行 fn；断路器跳闸或 fn 抛异常时返回 None。"""
        now = now or self._now()
        if not self.can_execute(source, now):
            return None
        try:
            result = fn()
        except Exception:
            self.record_failure(source, now)
            return None
        # 空 dict/list 视为失败
        if result is None or result == {} or result == []:
            self.record_failure(source, now)
            return None
        self.record_success(source, now)
        return result

    def health(self, source: str) -> SourceHealth:
        st = self._state(source)
        status = st.status
        if status == "half_open":
            status = "degraded"
        return SourceHealth(
            source=source,
            status=status,
            last_ok_at=st.last_ok_at,
            consecutive_failures=st.consecutive_failures,
            tripped_until=st.tripped_until,
        )

    def all_health(self, sources: list[str]) -> dict[str, SourceHealth]:
        return {s: self.health(s) for s in sources}


# 进程级单例
_registry = CircuitBreakerRegistry()


def get_breaker_registry() -> CircuitBreakerRegistry:
    return _registry
