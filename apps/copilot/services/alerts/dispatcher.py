"""AlertDispatcher：Redis Stream → 告警 → 三通道。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_05]
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.services.alerts.channels.base import BaseChannel, ChannelResult
from apps.copilot.services.alerts.dedup import AlertDeduper
from apps.copilot.services.alerts.models import Alert, AlertLog, AlertType
from apps.copilot.services.alerts.sla_monitor import SLAMonitor

logger = logging.getLogger(__name__)

PauseCheck = Optional[Callable[[], Awaitable[bool]]]

UPSTREAM_STREAMS = [
    "events:cryo_guard:reject",
    "events:cryo_guard:degrade",
    "events:exit:sell_signal",
    "events:monitor:health_change",
    "events:monitor:market_phase_change",
]

CONSUMER_GROUP = "copilot_alert_group"
CONSUMER_NAME = "copilot_alert_1"


def _parse_stream_fields(data: dict[Any, Any]) -> dict[str, Any]:
    """decode_responses=True 时为 str->str；兼容 bytes；支持 json/data 整包。"""
    out: dict[str, Any] = {}
    merged: dict[str, Any] | None = None
    for k, v in data.items():
        key = k.decode() if isinstance(k, bytes) else str(k)
        val = v.decode() if isinstance(v, bytes) else v
        if key in ("json", "data"):
            try:
                parsed = json.loads(val) if isinstance(val, str) else val
                if isinstance(parsed, dict):
                    merged = parsed
                    break
            except (TypeError, ValueError):
                out[key] = val
        else:
            try:
                out[key] = json.loads(val) if isinstance(val, str) else val
            except (TypeError, ValueError):
                out[key] = val
    return merged if merged is not None else out


def _node_state_dict(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("node_state")
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            p = json.loads(raw)
            return p if isinstance(p, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def map_event_to_alert(user_id: str, stream: str, event: dict[str, Any]) -> Alert | None:
    symbol = str(event.get("symbol", "?"))
    name = str(event.get("name", "?"))

    if stream == "events:cryo_guard:reject":
        reason = event.get("aggregation_reason", "防御引擎判定 reject")
        return Alert.new(
            user_id=user_id,
            alert_type=AlertType.REJECT,
            symbol=symbol,
            name=name,
            message=f"防御引擎拒绝：{reason}",
            payload=event,
        )

    if stream == "events:cryo_guard:degrade":
        return Alert.new(
            user_id=user_id,
            alert_type=AlertType.DEGRADE,
            symbol=symbol,
            name=name,
            message=f"防御引擎降级：{event.get('aggregation_reason', '风险升高')}",
            payload=event,
        )

    if stream == "events:exit:sell_signal":
        signal_type = str(event.get("signal_type", ""))
        advice = str(event.get("advice", "卖出条件触发，建议人工确认"))
        payload = {**event, "source_stream": stream}

        mapping: dict[str, tuple[AlertType, str, str]] = {
            "stop_loss": (
                AlertType.STOP_LOSS,
                "🔴",
                f"🔴 [diting] {name} {symbol} 止损触发 · 建议查看 thesis",
            ),
            "take_profit": (
                AlertType.TAKE_PROFIT,
                "🔴",
                f"🔴 [diting] {name} {symbol} 止盈触发 · 建议查看 thesis",
            ),
            "thesis_invalid": (
                AlertType.THESIS_INVALID,
                "🔴",
                f"🔴 [diting] {name} {symbol} Thesis 失效 · 建议清仓",
            ),
            "rebalance": (
                AlertType.REBALANCE,
                "🔴",
                f"🔴 [diting] {name} {symbol} 再平衡触发 · 建议减仓",
            ),
            "financial_window": (
                AlertType.FINANCIAL_WINDOW,
                "🟠",
                f"🟠 [diting] {name} {symbol} 财报窗口 · 请关注 SP5 建议",
            ),
        }
        entry = mapping.get(signal_type)
        if entry is None:
            return None
        alert_type, _emoji, subject = entry
        payload["email_subject"] = subject
        return Alert.new(
            user_id=user_id,
            alert_type=alert_type,
            symbol=symbol,
            name=name,
            message=advice,
            payload=payload,
        )

    if stream == "events:monitor:health_change":
        delta = float(event.get("health_delta", 0.0))
        ns = _node_state_dict(event)
        thesis_status = ns.get("thesis_status")
        if delta < -20.0:
            return Alert.new(
                user_id=user_id,
                alert_type=AlertType.HEALTH_DROP,
                symbol=symbol,
                name=name,
                message=f"健康度 24h 内骤降 {delta:.1f}：{event.get('change_reason', '')}",
                payload=event,
            )
        if thesis_status == "invalid":
            return Alert.new(
                user_id=user_id,
                alert_type=AlertType.THESIS_INVALID,
                symbol=symbol,
                name=name,
                message=f"Thesis 失效：{event.get('change_reason', '')}",
                payload=event,
            )
        return None

    if stream == "events:monitor:market_phase_change":
        new_phase = str(event.get("market_phase") or "")
        prev_phase = str(event.get("prev_market_phase") or "")
        conf = float(event.get("market_phase_confidence") or 0.0)
        advice = str(event.get("advice") or "")
        if new_phase == "exhaustion" and conf >= 0.65:
            return Alert.new(
                user_id=user_id,
                alert_type=AlertType.MARKET_PHASE_EXHAUSTION,
                symbol=symbol,
                name=name,
                message=f"市场阶段 → 利好透支（{prev_phase}→{new_phase}，置信度 {conf:.0%}）。{advice}",
                payload={
                    **event,
                    "email_subject": f"🔴 [diting] {name} {symbol} 进入利好透支 · 建议评估止盈",
                },
            )
        if prev_phase and new_phase != prev_phase:
            return Alert.new(
                user_id=user_id,
                alert_type=AlertType.MARKET_PHASE_SHIFT,
                symbol=symbol,
                name=name,
                message=f"市场阶段切换：{prev_phase} → {new_phase}（置信度 {conf:.0%}）。{advice}",
                payload={
                    **event,
                    "email_subject": f"[diting] {name} {symbol} 阶段切换 {prev_phase}→{new_phase}",
                },
            )
        return None

    return None


class AlertDispatcher:
    def __init__(
        self,
        redis: Redis | None,
        session_factory,
        channels: list[BaseChannel],
        deduper: AlertDeduper,
        sla_monitor: SLAMonitor,
        default_user_id: str = "default",
        pause_check: PauseCheck = None,
    ):
        self._redis = redis
        self._session_factory = session_factory
        self._channels = channels
        self._deduper = deduper
        self._sla = sla_monitor
        self._user = default_user_id
        self._stop = asyncio.Event()
        self._pause_check = pause_check

    def set_pause_check(self, fn: PauseCheck) -> None:
        self._pause_check = fn

    async def dispatch(
        self, alert: Alert, *, force: bool = False
    ) -> dict[str, dict] | dict[str, bool]:
        if (
            not force
            and self._pause_check is not None
            and alert.user_id != "architect"
        ):
            try:
                if await self._pause_check():
                    logger.info("circuit breaker open, skip dispatch alert=%s", alert.alert_id)
                    return {"circuit_open": True}
            except Exception as e:  # noqa: BLE001
                logger.warning("pause_check failed: %s", e)

        if await self._deduper.is_duplicate(alert):
            logger.info("dedup hit: %s", alert.dedup_key)
            return {"dedup": True}

        async with self._session_factory() as session:  # type: AsyncSession
            session.add(
                AlertLog(
                    alert_id=alert.alert_id,
                    user_id=alert.user_id,
                    level=alert.level.value,
                    alert_type=alert.alert_type.value,
                    symbol=alert.symbol,
                    name=alert.name,
                    message=alert.message,
                    payload=alert.payload,
                    dedup_key=alert.dedup_key,
                    channels_sent={},
                    sla_met=None,
                    latency_ms=None,
                    created_at=alert.created_at,
                )
            )
            await session.commit()

        dispatch_ts = self._sla.now()
        results: list[ChannelResult] = await asyncio.gather(
            *[ch.send(alert) for ch in self._channels], return_exceptions=False
        )
        for r in results:
            if not r.ok and r.reason and "[STUB]" in r.reason:
                logger.info("[STUB] channel=%s reason=%s", r.channel, r.reason)

        first_ok_ts: datetime | None = None
        for r in results:
            if r.ok and r.sent_at is not None:
                first_ok_ts = r.sent_at if first_ok_ts is None else min(first_ok_ts, r.sent_at)

        channels_result = {
            r.channel: {
                "ok": r.ok,
                "reason": r.reason,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            }
            for r in results
        }
        await self._sla.record(alert, dispatch_ts, first_ok_ts, channels_result)

        logger.info(
            "alert dispatched id=%s type=%s level=%s channels=%s",
            alert.alert_id,
            alert.alert_type.value,
            alert.level.value,
            channels_result,
        )
        return channels_result

    async def ensure_groups(self) -> None:
        if self._redis is None:
            return
        for stream in UPSTREAM_STREAMS:
            try:
                await self._redis.xgroup_create(stream, CONSUMER_GROUP, id="0", mkstream=True)
            except ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    logger.debug("xgroup_create skipped for %s: %s", stream, e)
            except Exception as e:  # noqa: BLE001
                logger.debug("xgroup_create skipped for %s: %s", stream, e)

    async def consume_forever(self, block_ms: int = 5000, count: int = 10) -> None:
        if self._redis is None:
            logger.warning("alert consume_forever: redis is None, idle")
            await self._stop.wait()
            return

        await self.ensure_groups()
        streams = {s: ">" for s in UPSTREAM_STREAMS}
        while not self._stop.is_set():
            try:
                entries = await self._redis.xreadgroup(
                    groupname=CONSUMER_GROUP,
                    consumername=CONSUMER_NAME,
                    streams=streams,
                    count=count,
                    block=block_ms,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("xreadgroup failed: %s; retry in 2s", e)
                await asyncio.sleep(2.0)
                continue

            if not entries:
                continue

            for stream_raw, messages in entries:
                stream = stream_raw.decode() if isinstance(stream_raw, bytes) else stream_raw
                for msg_id, data in messages:
                    try:
                        event = _parse_stream_fields(data)
                        alert = map_event_to_alert(self._user, stream, event)
                        if alert is not None:
                            await self.dispatch(alert)
                    except Exception:  # noqa: BLE001
                        logger.exception("handle %s failed", stream)
                    finally:
                        try:
                            await self._redis.xack(stream, CONSUMER_GROUP, msg_id)
                        except Exception as ack_e:  # noqa: BLE001
                            logger.warning("xack failed %s: %s", msg_id, ack_e)

    def stop(self) -> None:
        self._stop.set()
