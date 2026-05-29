"""B4 E2E：监控字典 → P5/P7 真流读 Redis 验证（1 只 watchlist）。

按 共享规约 20 §5.2 消费端时序：
  1. MonitorDictReader.has_dict(symbol) 校验 _meta 存在（MC1）
  2. fields_for_probe(symbol, "P5") / "P7" 拿 active 字段
  3. aggregate_keywords 聚合 keywords 注入探针
  4. 探针真流执行（读 cryo_guard.announcements）
  5. 探针返回中 monitor_keywords_used 字段可见

[Ref: 03_/_共享规约/20_监控字典规约.md §五]
[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_03]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import redis  # noqa: E402

from apps.state_watch.probes.monitor_dict_reader import (  # noqa: E402
    MonitorDictReader,
    aggregate_keywords,
    aggregate_source_urls,
)
from apps.state_watch.probes.physical.p5_tender import TenderProbe  # noqa: E402
from apps.state_watch.probes.physical.p7_capacity import CapacityProbe  # noqa: E402


def _load_redis_client() -> redis.Redis:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
    url = os.environ.get("SUPER_EVO_REDIS_URL", "redis://localhost:6379/5")
    client = redis.from_url(url, decode_responses=True)
    client.ping()
    return client


async def _run_e2e(symbol: str) -> dict:
    redis_client = _load_redis_client()
    reader = MonitorDictReader(redis_client)

    report: dict = {
        "symbol": symbol,
        "has_dict": reader.has_dict(symbol),
        "meta": reader.get_meta(symbol),
    }
    if not report["has_dict"]:
        report["status"] = "no_monitor_dict_skip(MC1)"
        return report

    p5_fields = reader.fields_for_probe(symbol, "P5")
    p7_fields = reader.fields_for_probe(symbol, "P7")

    p5_keywords = aggregate_keywords(p5_fields)
    p5_urls = aggregate_source_urls(p5_fields)
    p7_keywords = aggregate_keywords(p7_fields)

    report["fields_summary"] = {
        "P5_count": len(p5_fields),
        "P5_field_ids": [f.field_id for f in p5_fields],
        "P5_keywords": list(p5_keywords),
        "P5_source_urls": list(p5_urls),
        "P7_count": len(p7_fields),
        "P7_field_ids": [f.field_id for f in p7_fields],
        "P7_keywords": list(p7_keywords),
    }

    # 真流跑 P5（注入字典关键词增强）
    p5_probe = TenderProbe(monitor_keywords=p5_keywords)
    p5_result = await p5_probe.fetch(symbol)
    report["P5_probe_result"] = {
        "success": p5_result.success,
        "elapsed_ms": p5_result.elapsed_ms,
        **(p5_result.data or {}),
    }
    # MC3：如有 P5 alert 命中（physical_signal != red），mark 字段
    if p5_result.data.get("status") == "ok" and p5_result.data.get("physical_signal") in ("green", "yellow"):
        for f in p5_fields:
            reader.mark_field_hit(symbol, f.field_id)
        report["P5_mark_field_hit"] = [f.field_id for f in p5_fields]

    # 真流跑 P7（注入字典关键词增强）
    p7_probe = CapacityProbe(monitor_keywords=p7_keywords)
    p7_result = await p7_probe.fetch(symbol)
    report["P7_probe_result"] = {
        "success": p7_result.success,
        "elapsed_ms": p7_result.elapsed_ms,
        **(p7_result.data or {}),
    }
    if p7_result.data.get("status") == "ok" and p7_result.data.get("hit_via_monitor_keyword"):
        # MC3：命中字典关键词的 P7 alert，mark 关联字段
        for f in p7_fields:
            reader.mark_field_hit(symbol, f.field_id)
        report["P7_mark_field_hit"] = [f.field_id for f in p7_fields]

    report["status"] = "ok"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="B4 E2E: 监控字典 → P5/P7 真流验证")
    parser.add_argument(
        "--symbol",
        default="300308",
        help="待验证的 watchlist 标的（默认 300308 中际旭创）",
    )
    args = parser.parse_args()

    try:
        report = asyncio.run(_run_e2e(args.symbol))
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    # AKShare 不参与 → 不需要 _os._exit 兜底
    sys.exit(main())
