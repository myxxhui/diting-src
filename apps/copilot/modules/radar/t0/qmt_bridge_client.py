"""QMT 桥接 HTTP 客户端（可选 · 主源失败时 akshare 备源）。

[Ref: 27_ §2.4 T0-8 · P1 QMT 桥接]
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


class QmtBridgeClient:
    """``RADAR_QMT_BRIDGE_URL`` 指向 Windows/QMT 侧 HTTP 桥（如 ``http://host:8787``）。"""

    def __init__(self, base_url: str | None = None, *, timeout: float = 35.0) -> None:
        self.base_url = (base_url or os.environ.get("RADAR_QMT_BRIDGE_URL") or "").strip().rstrip("/")
        self.timeout = timeout

    def enabled(self) -> bool:
        return bool(self.base_url)

    def fetch_kline(self, symbol: str, *, days: int = 250) -> list[dict[str, Any]] | None:
        """GET ``/kline?symbol=&days=`` → [{date,open,high,low,close,volume}, ...]"""
        if not self.enabled():
            return None
        sym = str(symbol).zfill(6)[-6:]
        try:
            qs = urllib.parse.urlencode({"symbol": sym, "days": days})
            url = f"{self.base_url}/kline?{qs}"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            rows = data.get("bars") if isinstance(data, dict) else data
            if not isinstance(rows, list) or not rows:
                return None
            out: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                out.append(
                    {
                        "date": str(row.get("date") or ""),
                        "open": float(row.get("open") or 0),
                        "high": float(row.get("high") or 0),
                        "low": float(row.get("low") or 0),
                        "close": float(row.get("close") or 0),
                        "volume": float(row.get("volume") or 0),
                    }
                )
            if out:
                logger.info("QMT bridge K线 symbol=%s days=%d rows=%d", sym, days, len(out))
            return out or None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("QMT bridge K线失败 symbol=%s: %s", sym, exc)
            return None
