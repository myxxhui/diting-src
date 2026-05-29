"""监控字典只读 API（D3 消费端）。

[Ref: 03_/_共享规约/20_监控字典规约.md]
"""
from __future__ import annotations

import redis
from fastapi import APIRouter, HTTPException

from apps.state_watch.config import settings
from apps.state_watch.monitor_dict_reader import MonitorDictReader

router = APIRouter(prefix="/api/monitor-dict", tags=["monitor-dict"])


def _reader() -> MonitorDictReader:
    client = redis.from_url(settings.redis_url, decode_responses=True)
    return MonitorDictReader(client)


@router.get("/{symbol}")
async def get_monitor_fields(symbol: str, probe_id: str | None = None) -> dict:
    reader = _reader()
    meta = reader.load_meta(symbol)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"symbol {symbol} 无 monitor 字典")
    fields = reader.load_fields(symbol, probe_id=probe_id)
    return {"symbol": symbol, "meta": meta, "fields": fields, "count": len(fields)}


@router.get("/{symbol}/summary")
async def monitor_summary(symbol: str) -> dict:
    reader = _reader()
    return reader.weight_summary(symbol)
