"""P2·新闻探针(1h 调度).

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from apps.state_watch.probes.base_probe import BaseProbe, ProbeResult
from apps.state_watch.probes.datasource.news_adapter import NewsItem, fetch_recent_news


class NewsProbe(BaseProbe):
    probe_type = "news"
    timeout_seconds = 15.0
    interval_hours = 1

    async def _fetch_impl(self, symbol: str) -> dict[str, Any]:
        items = await asyncio.to_thread(fetch_recent_news, symbol, 7)
        if not items:
            return {
                "sentiment_score_7d": 0.0,
                "negative_count_7d": 0,
                "positive_count_7d": 0,
                "total_count_7d": 0,
                "latest_event": None,
            }
        return self._aggregate(items)

    def _aggregate(self, items: list[NewsItem]) -> dict[str, Any]:
        sentiments = [n.sentiment for n in items]
        neg = sum(1 for n in items if n.event_type == "negative")
        pos = sum(1 for n in items if n.event_type == "positive")
        avg = sum(sentiments) / len(sentiments) if sentiments else 0.0
        latest = max(items, key=lambda x: x.publish_time)
        return {
            "sentiment_score_7d": round(avg, 4),
            "negative_count_7d": neg,
            "positive_count_7d": pos,
            "total_count_7d": len(items),
            "latest_event": {
                "title": latest.title,
                "event_type": latest.event_type,
                "sentiment": latest.sentiment,
                "publish_time": latest.publish_time.isoformat(),
            },
        }


async def _cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()
    probe = NewsProbe()
    result: ProbeResult = await probe.fetch(args.symbol)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_cli())
