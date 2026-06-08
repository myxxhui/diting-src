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
    # 盘中 */5 · 9:00–14:55；15:00 收盘快照见 quote-intraday-close（禁止 15:05+ 空跑）
    ExecutingJobSpec("quote-intraday", "*/5 9-14 * * 1-5", True, True, 600),
    ExecutingJobSpec("quote-intraday-close", "0 15 * * 1-5", True, True, 600),
    ExecutingJobSpec("executing-bars250-bootstrap", "", True, False, 3600),
    # #16 15min K 线 · 与交易所 15m 收盘对齐（9:45 首根 + 10–11:30 + 13–15）
    ExecutingJobSpec("l4-vol-div-15m", "0,15,30,45 10-11,13-14 * * 1-5", True, True, 900),
    ExecutingJobSpec("l4-vol-div-15m-open", "45 9 * * 1-5", True, True, 900),
    ExecutingJobSpec("l4-vol-div-15m-close", "0 15 * * 1-5", True, True, 900),
    # #17 smart_money_flow · Tushare moneyflow（14:00 250日回填检查 · 17:00 日更）
    ExecutingJobSpec("l4-smart-money-backfill", "0 14 * * 1-5", True, True, 3600),
    ExecutingJobSpec("l4-smart-money-eod", "0 17 * * 1-5", True, True, 900),
    ExecutingJobSpec("l4-atr-bars-sync", "0 16 * * 1-5", True, True, 900),
    ExecutingJobSpec("l4-micro-eod", "10 16 * * 1-5", True, True, 1800),
    ExecutingJobSpec("l3-news-daily", "0 18 * * 1-5", True, True, 1800),
    ExecutingJobSpec("daily-pipeline", "45 18 * * 1-5", True, True, 3600),
    ExecutingJobSpec("bootstrap-sync", "", True, False, 3600),
    ExecutingJobSpec("collect-once", "", True, True, 3600),
)
