"""ProbeScheduler:统一管理 4 类探针调度.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_04_探针调度器与SLI聚合.md]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime
from typing import Optional

import redis.asyncio as redis_async
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.state_watch.config import settings
from apps.state_watch.db.models import HoldingState, NodeSLIValue, _uuid
from apps.state_watch.db.session import session_ctx
from apps.state_watch.events.health_change_publisher import map_score_to_state, publish_health_change
from apps.state_watch.health.sli_aggregator import SLIDef, _score_one, aggregate
from apps.state_watch.probes.base_probe import BaseProbe
from apps.state_watch.probes.event import EventProbe
from apps.state_watch.probes.financial import FinancialProbe
from apps.state_watch.probes.heartbeat import record as record_heartbeat
from apps.state_watch.probes.news import NewsProbe
from apps.state_watch.probes.price import PriceProbe
from apps.state_watch.state_machine.states import NodeState

# 两次 tick 之间 health_score 跌幅超过此阈值则发布 health_change
HEALTH_CHANGE_DROP_THRESHOLD = 10.0

logger = logging.getLogger(__name__)


class ProbeScheduler:
    """统一探针调度器."""

    def __init__(self, redis_client: Optional[redis_async.Redis] = None) -> None:
        self.scheduler = AsyncIOScheduler()
        self.redis = redis_client or redis_async.from_url(settings.redis_url, decode_responses=True)
        # 用于发布 health_change 到 D4（与 EXIT_REDIS_URL 同一 DB）
        self.exit_redis = redis_async.from_url(settings.exit_redis_url, decode_responses=True)
        self.probes: dict[str, BaseProbe] = {
            "financial": FinancialProbe(),
            "news": NewsProbe(),
            "price": PriceProbe(),
            "event": EventProbe(),
        }
        self._counters: dict[str, dict[str, int]] = {
            k: {"success": 0, "fail": 0} for k in self.probes
        }

    def register_jobs(self) -> None:
        self.scheduler.add_job(
            self._tick,
            kwargs={"probe_type": "price"},
            trigger=IntervalTrigger(minutes=30),
            id="probe-price-30m",
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            self._tick,
            kwargs={"probe_type": "news"},
            trigger=IntervalTrigger(hours=1),
            id="probe-news-1h",
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            self._tick,
            kwargs={"probe_type": "event"},
            trigger=IntervalTrigger(hours=6),
            id="probe-event-6h",
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            self._tick,
            kwargs={"probe_type": "financial"},
            trigger=CronTrigger(hour=9, minute=0),
            id="probe-financial-daily",
            max_instances=1,
            coalesce=True,
        )

    def start(self) -> None:
        self.register_jobs()
        self.scheduler.start()
        logger.info("ProbeScheduler started")

    def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)
        logger.info("ProbeScheduler stopped")

    async def _tick(self, probe_type: str) -> None:
        if probe_type == "price" and not _is_trading_hours():
            logger.debug("skip price tick: not trading hours")
            await record_heartbeat(
                self.redis,
                probe_type,
                status="skip",
                success_count=self._counters[probe_type]["success"],
                fail_count=self._counters[probe_type]["fail"],
            )
            return

        async with session_ctx() as session:
            nodes = await self._list_active_nodes(session)
        logger.info("tick probe=%s active_nodes=%s", probe_type, len(nodes))

        for node in nodes:
            await self._run_for_node(probe_type, node)

        await record_heartbeat(
            self.redis,
            probe_type,
            status="ok",
            success_count=self._counters[probe_type]["success"],
            fail_count=self._counters[probe_type]["fail"],
        )

    async def _run_for_node(self, probe_type: str, node: HoldingState) -> None:
        probe = self.probes[probe_type]
        result = await probe.fetch(node.symbol)

        if not result.success:
            self._counters[probe_type]["fail"] += 1
            return
        self._counters[probe_type]["success"] += 1

        target_metrics = [s for s in (node.slis or []) if s.get("probe_type") == probe_type]
        if not target_metrics:
            return

        prev_score = node.health_score
        async with session_ctx() as session:
            for sli in target_metrics:
                metric = sli.get("metric")
                value = result.data.get(metric)
                if value is None:
                    continue
                await self._upsert_sli_value(session, node, sli, float(value), result.fetched_at)
            await session.commit()

        # 重新计算最新 health_score 并判断是否需要通知 D4
        await self._maybe_publish_health_change(node, probe_type, prev_score)

    async def _upsert_sli_value(
        self,
        session: AsyncSession,
        node: HoldingState,
        sli: dict,
        value: float,
        fetched_at: datetime,
    ) -> None:
        stmt = select(NodeSLIValue).where(
            NodeSLIValue.holding_id == node.id,
            NodeSLIValue.metric == sli["metric"],
        )
        res = await session.execute(stmt)
        row = res.scalar_one_or_none()

        sd = _score_one(
            SLIDef(
                id=sli.get("id", sli["metric"]),
                metric=sli["metric"],
                threshold=float(sli.get("threshold", 0.0)),
                operator=sli.get("operator", ">"),
                weight=float(sli.get("weight", 1.0)),
                probe_type=sli.get("probe_type", "financial"),
                current_value=value,
            )
        )

        if row is None:
            row = NodeSLIValue(
                id=_uuid(),
                holding_id=node.id,
                sli_id=sli.get("id", sli["metric"]),
                metric=sli["metric"],
                probe_type=sli.get("probe_type", "financial"),
                threshold=float(sli.get("threshold", 0.0)),
                operator=sli.get("operator", ">"),
                weight=float(sli.get("weight", 1.0)),
                current_value=value,
                last_score=sd.score,
                last_updated=fetched_at,
            )
            session.add(row)
        else:
            row.current_value = value
            row.last_score = sd.score
            row.last_updated = fetched_at

    async def _maybe_publish_health_change(
        self,
        node: HoldingState,
        probe_type: str,
        prev_score: float,
    ) -> None:
        """若 health_score 跌幅超过阈值，向 D4 发布 health_change 事件。"""
        async with session_ctx() as session:
            from sqlalchemy import select as sa_select
            rows = (
                await session.execute(
                    sa_select(NodeSLIValue).where(NodeSLIValue.holding_id == node.id)
                )
            ).scalars().all()

        sli_defs = [
            SLIDef(
                id=r.sli_id,
                metric=r.metric,
                threshold=r.threshold,
                operator=r.operator,
                weight=r.weight,
                probe_type=r.probe_type,
                current_value=r.current_value,
            )
            for r in rows
        ]
        new_score, _ = aggregate(sli_defs)

        drop = prev_score - new_score
        if drop < HEALTH_CHANGE_DROP_THRESHOLD:
            return

        new_state = map_score_to_state(new_score)
        await publish_health_change(
            self.exit_redis,
            symbol=node.symbol,
            new_state=new_state,
            health_score=new_score,
            prev_score=prev_score,
            source_probe=probe_type,
        )

    @staticmethod
    async def _list_active_nodes(session: AsyncSession) -> list[HoldingState]:
        stmt = select(HoldingState).where(HoldingState.state != NodeState.EXIT.value)
        res = await session.execute(stmt)
        return list(res.scalars().all())


def _is_trading_hours(now: Optional[datetime] = None) -> bool:
    now = now or datetime.utcnow()
    if now.weekday() >= 5:
        return False
    cn_time = (now.hour + 8) % 24
    if cn_time < 9 or cn_time > 15:
        return False
    if cn_time == 11 and now.minute > 30:
        return False
    if cn_time == 12:
        return False
    return True


async def _run_once() -> None:
    """一次性触发四类探针 tick（供手工验证）。"""
    sched = ProbeScheduler()
    for ptype in ("financial", "news", "price", "event"):
        await sched._tick(ptype)


async def _run_forever() -> None:
    sched = ProbeScheduler()
    sched.start()
    try:
        await asyncio.Event().wait()
    finally:
        sched.shutdown()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.once:
        asyncio.run(_run_once())
        return
    if args.start:
        try:
            asyncio.run(_run_forever())
        except KeyboardInterrupt:
            pass
        return
    parser.print_help()


if __name__ == "__main__":
    main()
