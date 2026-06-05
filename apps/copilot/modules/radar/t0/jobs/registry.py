"""§2.8.2 T0 CronJob 注册表。

[Ref: 27_ §2.8.2]
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class JobScope(str, Enum):
    GLOBAL = "global"
    COLLECT = "collect"  # load_generic_t0_collect_symbols()


class JobCadence(str, Enum):
    INTRADAY = "intraday"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    ONESHOT = "oneshot"


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    t0_ids: tuple[int, ...]
    scope: JobScope
    cadence: JobCadence
    cron: str  # 上海时区 · Helm 用
    description: str
    active_deadline_seconds: int = 1800
    implemented: bool = False
    micro_key: str | None = None  # per-symbol 微观 collector 写入 cache 的键
    domain_key: str | None = None  # ecosystem/consensus/risk 子键（非 micro）


# job_id 与 §2.8.2 表 1:1（连字符）
JOB_REGISTRY: tuple[JobSpec, ...] = (
    JobSpec(
        "sentiment-intraday",
        (1,),
        JobScope.GLOBAL,
        JobCadence.INTRADAY,
        "*/10 9-15 * * 1-5",
        "两市成交额/涨跌比/连板 → Redis",
        active_deadline_seconds=600,
        implemented=True,
    ),
    JobSpec(
        "sentiment-eod",
        (1,),
        JobScope.GLOBAL,
        JobCadence.DAILY,
        "30 15 * * 1-5",
        "日定稿 → PG + Redis",
        active_deadline_seconds=600,
        implemented=True,
    ),
    JobSpec(
        "macro-sector-daily",
        (2, 3),
        JobScope.COLLECT,
        JobCadence.DAILY,
        "0 16 * * 1-5",
        "表内标的→板块去重 · 3日涨跌+资金",
        implemented=True,
    ),
    JobSpec(
        "ecosystem-peer-daily",
        (7,),
        JobScope.COLLECT,
        JobCadence.DAILY,
        "0 17 * * 1-5",
        "同业 Top5 市值重排",
        implemented=True,
        domain_key="peer_ranking",
    ),
    JobSpec(
        "micro-margin-daily",
        (10,),
        JobScope.COLLECT,
        JobCadence.DAILY,
        "0 9 * * 1-5",
        "融资融券 T-1",
        implemented=True,
        micro_key="margin",
    ),
    JobSpec(
        "micro-dragon-daily",
        (11,),
        JobScope.COLLECT,
        JobCadence.DAILY,
        "30 17 * * 1-5",
        "龙虎榜近 10 日",
        implemented=True,
        micro_key="dragon_tiger",
    ),
    JobSpec(
        "micro-northbound-daily",
        (9,),
        JobScope.COLLECT,
        JobCadence.DAILY,
        "0 18 * * 1-5",
        "陆股通 30 日",
        implemented=True,
        micro_key="northbound",
    ),
    JobSpec(
        "risk-regulatory-daily",
        (17,),
        JobScope.COLLECT,
        JobCadence.DAILY,
        "0 20 * * 1-5",
        "监管公告",
        implemented=True,
        domain_key="regulatory_events",
    ),
    JobSpec(
        "consensus-weekly",
        (12, 13),
        JobScope.COLLECT,
        JobCadence.WEEKLY,
        "0 10 * * 6",
        "一致预期 + 评级",
        active_deadline_seconds=3600,
        implemented=True,
    ),
    JobSpec(
        "risk-pledge-unlock-weekly",
        (15, 16),
        JobScope.COLLECT,
        JobCadence.WEEKLY,
        "0 8 * * 6",
        "质押 + 解禁",
        active_deadline_seconds=3600,
        implemented=True,
    ),
    JobSpec(
        "ecosystem-profile-monthly",
        (4,),
        JobScope.COLLECT,
        JobCadence.MONTHLY,
        "0 2 1 * *",
        "档案/概念",
        active_deadline_seconds=3600,
        implemented=True,
        domain_key="profile",
    ),
    JobSpec(
        "ecosystem-segments-quarterly",
        (5,),
        JobScope.COLLECT,
        JobCadence.QUARTERLY,
        "0 3 1 5,9,11 *",
        "主营结构",
        active_deadline_seconds=3600,
        implemented=True,
        domain_key="segment_breakdown",
    ),
    JobSpec(
        "ecosystem-supply-chain-annual",
        (6,),
        JobScope.COLLECT,
        JobCadence.ANNUAL,
        "0 4 10 5 *",
        "供应链",
        active_deadline_seconds=3600,
        implemented=True,
        domain_key="supply_chain",
    ),
    JobSpec(
        "risk-financials-quarterly",
        (14,),
        JobScope.COLLECT,
        JobCadence.QUARTERLY,
        "0 5 1 5,9,11 *",
        "财务排雷",
        active_deadline_seconds=3600,
        implemented=True,
        domain_key="financial_slice",
    ),
    JobSpec(
        "bars-reconcile-daily",
        (8,),
        JobScope.COLLECT,
        JobCadence.DAILY,
        "0 19 * * 1-5",
        "K 线盘后对账",
        implemented=True,
        micro_key="bars_250d",
    ),
    JobSpec(
        "collect-once",
        (4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17),
        JobScope.COLLECT,
        JobCadence.ONESHOT,
        "",
        "前端/API 一次性全量 T0",
        implemented=True,
    ),
    JobSpec(
        "sentiment-backfill",
        (1,),
        JobScope.GLOBAL,
        JobCadence.ONESHOT,
        "",
        "近 N 交易日 T0-1 日表补录（交易所成交额+环比）",
        active_deadline_seconds=900,
        implemented=True,
    ),
    JobSpec(
        "bootstrap-sync",
        tuple(range(1, 18)),
        JobScope.COLLECT,
        JobCadence.ONESHOT,
        "",
        "冷启动缺口补同步",
        active_deadline_seconds=3600,
        implemented=True,
    ),
)


def get_job_spec(job_id: str) -> JobSpec:
    key = (job_id or "").strip()
    for spec in JOB_REGISTRY:
        if spec.job_id == key:
            return spec
    raise KeyError(f"未知 radar T0 job_id: {job_id}")


def cron_jobs() -> tuple[JobSpec, ...]:
    """Helm CronJob 列表（排除 oneshot）。"""
    return tuple(s for s in JOB_REGISTRY if s.cadence != JobCadence.ONESHOT and s.job_id != "bootstrap-sync")


def implemented_collectors() -> dict[str, str]:
    out: dict[str, str] = {}
    for s in JOB_REGISTRY:
        if s.micro_key:
            out[s.job_id] = s.micro_key
        elif s.domain_key:
            out[s.job_id] = s.domain_key
    return out
