"""Z0 段 A Cron / bootstrap Job 注册。

[Ref: 29_ §1.4 · 34_ §3.0b]
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Z0JobSpec:
    job_id: str
    cron: str = ""
    description: str = ""
    implemented: bool = True


Z0_JOB_REGISTRY: tuple[Z0JobSpec, ...] = (
    Z0JobSpec("z0-bootstrap-all", "", "首次 M1→M5→M2→M0 全链采集+合成"),
    Z0JobSpec("z0-m1-macro", "0 7 * * *", "宏观 PMI/CPI-PPI"),
    Z0JobSpec("z0-m5-liquidity", "30 7 * * 1-5", "北向+liquidity_regime"),
    Z0JobSpec("z0-policy-ingest", "45 7 * * 1-5", "政策 T0 ingest + T1 enum → DeepSea"),
    Z0JobSpec("z0-m2-sector-heat", "0 8 * * 1-5", "概念板块+政策赛道→候选"),
    Z0JobSpec("z0-m0-wind-scan", "15 8 * * 1-5", "M0 wind_scan 合成"),
)
