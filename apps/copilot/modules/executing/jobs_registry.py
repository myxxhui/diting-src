"""§4.4 CronJob 注册。

[Ref: 28_ §4.4]
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutingJobSpec:
    job_id: str
    cron: str
    implemented: bool = True
    per_symbol: bool = True
    active_deadline_seconds: int = 1800


JOB_REGISTRY: tuple[ExecutingJobSpec, ...] = (
    ExecutingJobSpec("quote-intraday", "*/5 9-15 * * 1-5", True, True, 600),
    ExecutingJobSpec("l4-micro-eod", "10 16 * * 1-5", True, True, 1800),
    ExecutingJobSpec("l3-news-daily", "0 18 * * 1-5", True, True, 1800),
    ExecutingJobSpec("daily-pipeline", "45 18 * * 1-5", True, True, 3600),
    ExecutingJobSpec("bootstrap-sync", "", True, False, 3600),
    ExecutingJobSpec("collect-once", "", True, True, 3600),
)
