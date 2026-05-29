#!/usr/bin/env python3
"""D3 step_03 · P3/P4 探针批量 + 交易时段检查.

[Ref: 03_/03_维度三/.../step_03 §7.2]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from apps.common.holdings_sot import load_holdings_sot
from apps.state_watch.probes.datasource.quote_adapter import fetch_bars_60d
from apps.state_watch.probes.event import EventProbe
from apps.state_watch.probes.monitor_dict_reader import (
    MonitorDictReader,
    aggregate_keywords,
)
from apps.state_watch.probes.physical.p5_tender import TenderProbe
from apps.state_watch.probes.physical.p6_customs import CustomsProbe
from apps.state_watch.probes.physical.p7_capacity import CapacityProbe
from apps.state_watch.probes.price import PriceProbe, compute_price_metrics


def _load_monitor_reader() -> MonitorDictReader | None:
    """连接 Redis monitor 字典；失败时返回 None（MC1：不阻塞探针）。"""
    try:
        import redis
        from dotenv import load_dotenv

        repo = Path(__file__).resolve().parents[1]
        load_dotenv(repo / ".env", override=False)
        url = os.getenv("SUPER_EVO_REDIS_URL", "redis://localhost:6379/5")
        client = redis.from_url(url, decode_responses=True)
        client.ping()
        return MonitorDictReader(client)
    except Exception as exc:
        print(f"[watch_step03] Redis monitor 字典不可用，探针用默认关键词: {exc}", file=sys.stderr)
        return None


async def _run_price(symbols: list[str]) -> dict:
    probe = PriceProbe()
    rows = []
    for sym in symbols:
        result = await probe.fetch(sym)
        metrics = result.data if result.success else {}
        non_null = sum(1 for k in ("pct_change_1d", "drawdown_60d", "rsi_14") if metrics.get(k) is not None)
        rows.append(
            {
                "symbol": sym,
                "success": result.success,
                "metrics_non_null": non_null,
                "error": result.error,
            }
        )
    ok = sum(1 for r in rows if r["success"])
    return {"probe": "P3", "total": len(rows), "ok": ok, "rows": rows}


async def _run_event(symbols: list[str]) -> dict:
    probe = EventProbe()
    rows = []
    for sym in symbols:
        result = await probe.fetch(sym)
        rows.append(
            {
                "symbol": sym,
                "success": result.success,
                "metrics": result.data if result.success else {},
                "error": result.error,
            }
        )
    ok = sum(1 for r in rows if r["success"])
    return {"probe": "P4", "total": len(rows), "ok": ok, "rows": rows}


def _trade_window_check() -> dict:
    from datetime import datetime, timezone

    from apps.state_watch.probes.scheduler import _is_trading_hours

    now_open = _is_trading_hours(datetime.now(timezone.utc))
    return {"is_trading_session": now_open, "ok": True}


async def _run_physical(probe_id: str, symbols: list[str]) -> dict:
    """运行物理探针 P5/P6/P7；P5/P7 从 Redis monitor 字典注入 keywords（共享规约 20 §5.2）。"""
    reader = _load_monitor_reader()
    pid = probe_id.upper()

    rows = []
    for sym in symbols:
        keywords: tuple[str, ...] = ()
        if reader is not None and pid in ("P5", "P7"):
            fields = reader.fields_for_probe(sym, pid)  # type: ignore[arg-type]
            keywords = aggregate_keywords(fields)

        if pid == "P5":
            probe = TenderProbe(monitor_keywords=keywords)
        elif pid == "P6":
            probe = CustomsProbe()
        elif pid == "P7":
            probe = CapacityProbe(monitor_keywords=keywords)
        else:
            return {"probe": probe_id, "status": "unknown_probe", "ok": False}

        result = await probe.fetch(sym)
        data = result.data if result.success else {"error": result.error}
        rows.append({"symbol": sym, "success": result.success, **data})

    ok_count = sum(1 for r in rows if r.get("success"))
    return {
        "probe": probe_id,
        "total": len(rows),
        "ok": ok_count,
        "monitor_dict_connected": reader is not None,
        "rows": rows,
    }


async def _main(mode: str) -> int:
    sot = load_holdings_sot()
    symbols = sot.active_symbols()
    if mode != "trade-window-check" and not symbols:
        print("❌ SoT 无 active 标的", file=sys.stderr)
        return 1
    if mode == "price":
        report = await _run_price(symbols)
    elif mode == "event":
        report = await _run_event(symbols)
    elif mode == "trade-window-check":
        report = _trade_window_check()
    elif mode in ("physical-p5", "physical-p6", "physical-p7", "physical-all", "physical-status"):
        if mode == "physical-all":
            parts = []
            for p in ("P5", "P6", "P7"):
                parts.append(await _run_physical(p, symbols))
            report = {"physical": parts, "ok": True}
        elif mode == "physical-status":
            report = {"physical_probes": ["P5_tender", "P6_customs", "P7_capacity"], "status": "active", "ok": True}
        else:
            pid = mode.split("-")[-1].upper()
            report = await _run_physical(pid, symbols)
    else:
        print(f"未知 mode: {mode}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if mode in ("price", "event"):
        ok = report.get("ok", 0) == report.get("total", 0)
    else:
        ok = report.get("ok", True)
    rc = 0 if ok else 1
    if mode.startswith("physical"):
        # AKShare 线程可能悬挂导致 asyncio cleanup 卡住，强制退出以免 Makefile 阻塞
        import os as _os
        sys.stdout.flush()
        sys.stderr.flush()
        _os._exit(rc)
    return rc


def _run_no_executor_drain(coro) -> int:
    """运行协程，不等待 executor 线程全部退出（避免 AKShare 悬挂线程卡住进程）。

    physical 模式下 P6 会向线程池提交 AKShare 网络请求；asyncio.run() 默认在退出时
    drain executor，若 AKShare 线程仍等待 TCP 响应则会阻塞分钟级。
    这里使用低层 API 跳过 shutdown_default_executor()。
    """
    import concurrent.futures

    loop = asyncio.new_event_loop()
    # 使用专属 executor，shutdown(wait=False) 不阻塞
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=8, thread_name_prefix="probe-akshare"
    )
    loop.set_default_executor(executor)
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        executor.shutdown(wait=False)  # 放弃等待悬挂的 AKShare 线程
        loop.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=[
            "price",
            "event",
            "trade-window-check",
            "physical-p5",
            "physical-p6",
            "physical-p7",
            "physical-all",
            "physical-status",
        ],
    )
    args = parser.parse_args()
    # physical 模式含 AKShare 线程，走不等 drain 的 runner
    if args.mode.startswith("physical"):
        raise SystemExit(_run_no_executor_drain(_main(args.mode)))
    raise SystemExit(asyncio.run(_main(args.mode)))


if __name__ == "__main__":
    main()
