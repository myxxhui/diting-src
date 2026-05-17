"""Copilot FastAPI 入口。

[Ref: 03_/00_维度零/.../step_02]
[Ref: 03_/00_维度零/.../step_03]
[Ref: 03_/00_维度零/.../step_06 M4 价值账本]
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from apps.copilot.config import settings
from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.modules.health_check import routes as health_routes
from apps.copilot.routers import portfolio
from apps.copilot.routers.alerts import router as alerts_router, view_router as alerts_view_router
from apps.copilot.routers.value import router as value_router, view_router as value_view_router
from apps.copilot.services.alerts.channels.email import EmailChannel
from apps.copilot.services.alerts.channels.telegram import TelegramChannel
from apps.copilot.services.alerts.channels.wechat import WechatChannel
from apps.copilot.services.alerts.dedup import AlertDeduper
from apps.copilot.services.alerts.dispatcher import AlertDispatcher
from apps.copilot.services.alerts.sla_monitor import SLAMonitor
from apps.copilot.services.ledger.circuit_breaker import CircuitBreaker
from apps.copilot.services.ledger.ev import EVCalculator
from apps.copilot.services.ledger.monthly_report import MonthlyReportGenerator
from apps.copilot.services.ledger.response_recorder import UserResponseRecorder
from apps.copilot.services.ledger.scheduler import LedgerScheduler
from apps.copilot.services.ledger.scs import SCSCalculator

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    app.state.templates = templates
    app.state.session_factory = AsyncSessionLocal

    channels = [
        WechatChannel(settings.wechat_webhook),
        TelegramChannel(settings.telegram_bot_token, settings.telegram_chat_id),
        EmailChannel(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            sender=settings.smtp_from,
            recipient=settings.smtp_to,
        ),
    ]
    deduper = AlertDeduper(AsyncSessionLocal, window_seconds=settings.alert_dedup_window)
    sla = SLAMonitor(AsyncSessionLocal, red_sla_seconds=settings.alert_red_sla)
    dispatcher = AlertDispatcher(
        app.state.redis,
        AsyncSessionLocal,
        channels,
        deduper,
        sla,
    )
    app.state.alert_dispatcher = dispatcher

    async def _arch_notifier(title: str, body: str) -> None:
        from apps.copilot.services.alerts.models import Alert, AlertType

        alert = Alert.new(
            user_id="architect",
            alert_type=AlertType.DEGRADE,
            symbol="SYSTEM",
            name="ValueLedger",
            message=f"{title} | {body}",
            payload={"source": "circuit_breaker"},
        )
        await app.state.alert_dispatcher.dispatch(alert)

    scs_calc = SCSCalculator(AsyncSessionLocal)
    ev_calc = EVCalculator(AsyncSessionLocal)
    breaker = CircuitBreaker(
        AsyncSessionLocal,
        window_size=settings.circuit_window,
        bh_threshold=settings.circuit_bh_threshold,
        notifier=_arch_notifier,
    )
    dispatcher.set_pause_check(breaker.is_paused)

    recorder = UserResponseRecorder(AsyncSessionLocal)
    report_gen = MonthlyReportGenerator(
        AsyncSessionLocal,
        scs_calc,
        ev_calc,
        reports_dir=settings.ledger_reports_dir,
        template_dir=str(BASE_DIR / "templates"),
        css_path=str(BASE_DIR / "static/css/monthly_report.css"),
        base_url=str(BASE_DIR),
    )
    scheduler = LedgerScheduler(
        report_gen,
        user_ids=["default"],
        cron_day=settings.monthly_cron_day,
        cron_hour=settings.monthly_cron_hour,
    )
    if settings.ledger_scheduler_enabled:
        scheduler.start()
        await scheduler.backfill_previous_month_if_missing(AsyncSessionLocal)

    app.state.ledger = {
        "scs": scs_calc,
        "ev": ev_calc,
        "breaker": breaker,
        "recorder": recorder,
        "report": report_gen,
        "scheduler": scheduler,
    }

    if settings.alert_consumer_enabled:
        app.state.alert_consumer_task = asyncio.create_task(dispatcher.consume_forever())
    else:
        app.state.alert_consumer_task = None

    yield

    ledger = getattr(app.state, "ledger", None)
    if ledger and ledger.get("scheduler"):
        ledger["scheduler"].stop()

    dispatcher.stop()
    task = getattr(app.state, "alert_consumer_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await app.state.redis.aclose()


app = FastAPI(title="AI 投资副驾驶", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(portfolio.router)
app.include_router(health_routes.router)
app.include_router(alerts_router)
app.include_router(alerts_view_router)
app.include_router(value_router)
app.include_router(value_view_router)


@app.get("/health")
async def health():
    upstream_status = {}
    for stream in settings.upstream_streams:
        try:
            info = await app.state.redis.xinfo_stream(stream)
            upstream_status[stream] = {"ok": True, "length": info.get("length", 0)}
        except Exception as e:  # noqa: BLE001
            err = str(e).lower()
            if "no such key" in err or "does not exist" in err:
                upstream_status[stream] = {
                    "ok": False,
                    "reason": "stream not found (mock mode)",
                }
            else:
                upstream_status[stream] = {"ok": False, "reason": str(e)}

    return {
        "status": "ok",
        "service": settings.service_name,
        "upstream": upstream_status,
    }
