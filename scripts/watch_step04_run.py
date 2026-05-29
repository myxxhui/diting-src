#!/usr/bin/env python3
"""D3 step_04 · 探针调度器 + SLI 聚合 Makefile 驱动.

[Ref: 03_/03_维度三/.../step_04 §7.2]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml
from sqlalchemy import func, select

from apps.common.holdings_sot import load_holdings_sot
from apps.state_watch.config import settings
from apps.state_watch.db.models import HoldingState, NodeSLIValue
from apps.state_watch.db.session import init_db, session_ctx
from apps.state_watch.health.sli_aggregator import SLIDef, aggregate
from apps.state_watch.probes.heartbeat import get_all
from apps.state_watch.probes.scheduler import ProbeScheduler, _run_once
from apps.state_watch.state_machine.registry import list_active_nodes, register_node

_AGG_YAML = Path(__file__).resolve().parents[1] / "apps/state_watch/configs/probe_aggregator.yaml"


def _load_aggregator_yaml() -> dict:
    if not _AGG_YAML.is_file():
        return {}
    raw = yaml.safe_load(_AGG_YAML.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


async def _ensure_holdings_from_sot() -> dict:
    """SoT active → holdings_state（缺则注册 + 默认 slis）."""
    sot = load_holdings_sot()
    symbols = sot.active_symbols()
    yaml_cfg = _load_aggregator_yaml()
    default_slis = yaml_cfg.get("default_slis") or {}
    flat_slis: list[dict] = []
    for probe_type, items in default_slis.items():
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    flat_slis.append({**item, "probe_type": item.get("probe_type", probe_type)})

    import redis.asyncio as redis_async

    redis_client = redis_async.from_url(settings.redis_url, decode_responses=True)
    created = 0
    async with session_ctx() as session:
        existing = await list_active_nodes(session)
        by_symbol = {h.symbol: h for h in existing}
        for entry in sot.holdings:
            if not entry.active:
                continue
            sym = entry.symbol.zfill(6)[-6:]
            if sym in by_symbol:
                if not by_symbol[sym].slis and flat_slis:
                    by_symbol[sym].slis = flat_slis
                    created += 0
                continue
            await register_node(
                session,
                redis_client,
                symbol=sym,
                name=entry.name or sym,
                thesis_id=f"sot-{sym}",
                thesis_summary=f"SoT 启动期 {sym}",
                slis=flat_slis,
            )
            created += 1
        await session.commit()
        total = len(await list_active_nodes(session))
    await redis_client.aclose()
    return {"active_symbols": len(symbols), "nodes_total": total, "nodes_created": created}


async def _run_prep() -> dict:
    yaml_ok = _AGG_YAML.is_file()
    await init_db()
    sync = await _ensure_holdings_from_sot()
    async with session_ctx() as session:
        n = await session.scalar(select(func.count()).select_from(NodeSLIValue))
    return {
        "probe_aggregator_yaml": str(_AGG_YAML),
        "yaml_ok": yaml_ok,
        "node_sli_values_rows": int(n or 0),
        **sync,
    }


async def _run_once_all() -> dict:
    await _ensure_holdings_from_sot()
    before = 0
    async with session_ctx() as session:
        before = int(await session.scalar(select(func.count()).select_from(NodeSLIValue)) or 0)
    await _run_once()
    async with session_ctx() as session:
        after = int(await session.scalar(select(func.count()).select_from(NodeSLIValue)) or 0)
    return {"node_sli_before": before, "node_sli_after": after, "delta": after - before}


async def _run_aggregate() -> dict:
    yaml_cfg = _load_aggregator_yaml()
    async with session_ctx() as session:
        nodes = await list_active_nodes(session)
        rows = []
        for node in nodes:
            stmt = select(NodeSLIValue).where(NodeSLIValue.holding_id == node.id)
            sli_rows = (await session.execute(stmt)).scalars().all()
            defs = [
                SLIDef(
                    id=r.sli_id,
                    metric=r.metric,
                    threshold=float(r.threshold),
                    operator=r.operator,
                    weight=float(r.weight),
                    probe_type=r.probe_type,
                    current_value=r.current_value,
                )
                for r in sli_rows
            ]
            score, details = aggregate(defs)
            rows.append(
                {
                    "symbol": node.symbol,
                    "sli_count": len(defs),
                    "sli_score": score,
                    "detail_scores": [d.score for d in details],
                }
            )
    return {
        "weights": yaml_cfg.get("weights"),
        "active_nodes": len(rows),
        "scores": rows,
    }


async def _run_scheduler_up(seconds: int = 5) -> dict:
    import redis.asyncio as redis_async

    await _ensure_holdings_from_sot()
    redis_client = redis_async.from_url(settings.redis_url, decode_responses=True)
    sched = ProbeScheduler(redis_client=redis_client)
    sched.register_jobs()
    sched.start()
    await asyncio.sleep(seconds)
    sched.shutdown()
    heartbeats = await get_all(redis_client)
    await redis_client.aclose()
    return {"ran_seconds": seconds, "heartbeat_count": len(heartbeats), "heartbeats": heartbeats}


async def _run_status() -> dict:
    import redis.asyncio as redis_async

    redis_client = redis_async.from_url(settings.redis_url, decode_responses=True)
    heartbeats = await get_all(redis_client)
    await redis_client.aclose()
    async with session_ctx() as session:
        nodes = await list_active_nodes(session)
        n_sli = int(await session.scalar(select(func.count()).select_from(NodeSLIValue)) or 0)
    return {
        "active_nodes": len(nodes),
        "node_sli_values_rows": n_sli,
        "heartbeats": heartbeats,
    }


async def _main(mode: str, seconds: int) -> int:
    if mode == "prep":
        out = await _run_prep()
    elif mode == "migrate":
        await init_db()
        out = {"migrate": "ok"}
    elif mode == "once-all":
        out = await _run_once_all()
    elif mode == "aggregate":
        out = await _run_aggregate()
    elif mode == "scheduler-up":
        out = await _run_scheduler_up(seconds=seconds)
    elif mode == "status":
        out = await _run_status()
    else:
        print(f"unknown mode: {mode}", file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if mode == "prep" and not out.get("yaml_ok"):
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=["prep", "migrate", "once-all", "aggregate", "scheduler-up", "status"],
    )
    parser.add_argument("--seconds", type=int, default=5)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.mode, args.seconds)))


if __name__ == "__main__":
    main()
