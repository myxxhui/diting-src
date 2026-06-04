"""将 Cron 采集结果合并进标的 T0 文件缓存。

[Ref: 27_ §2.8 · P2/P3 写文件缓存]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.copilot.modules.radar.t0_cache import load_cached, save_cache

logger = logging.getLogger(__name__)


def _base_bundle(sym: str, source: str) -> dict[str, Any]:
    return {
        "symbol": sym,
        "name": sym,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
    }


def merge_micro_into_cache(symbol: str, micro_key: str, payload: dict[str, Any]) -> None:
    """UPSERT ``micro.{micro_key}`` 到 latest bundle（不要求 fresh）。"""
    merge_domain_patch(symbol, "micro", {micro_key: payload}, source="cron:micro")


def merge_domain_patch(
    symbol: str,
    domain: str,
    patch: dict[str, Any],
    *,
    source: str = "cron:domain",
) -> None:
    """UPSERT ``{domain}.{key}`` 子树。"""
    sym = str(symbol).zfill(6)[-6:]
    bundle = load_cached(sym, require_fresh=False) or _base_bundle(sym, source)
    block = dict(bundle.get(domain) or {})
    block.update(patch)
    bundle[domain] = block
    if domain == "ecosystem" and "profile" in patch:
        bundle["profile"] = patch["profile"]
    bundle["symbol"] = sym
    if not bundle.get("collected_at"):
        bundle["collected_at"] = datetime.now(timezone.utc).isoformat()
    save_cache(bundle)
    logger.info(
        "domain cache merge symbol=%s domain=%s keys=%s",
        sym,
        domain,
        list(patch.keys()),
    )


def merge_macro_sector(symbol: str, sector_ctx: dict[str, Any]) -> None:
    """合并 T0-2/3 板块块到 macro（并注入全局 T0-1 快照）。"""
    sym = str(symbol).zfill(6)[-6:]
    bundle = load_cached(sym, require_fresh=False) or _base_bundle(sym, "cron:sector")
    macro = dict(bundle.get("macro") or {})
    ms = read_global_macro_cache()
    if ms and ms.get("status") == "ok":
        macro["market_sentiment"] = ms
    for key in ("sector_momentum", "sector_flow"):
        if key in sector_ctx:
            macro[key] = sector_ctx[key]
    bundle["macro"] = macro
    bundle["symbol"] = sym
    save_cache(bundle)


def write_global_macro_cache(payload: dict[str, Any]) -> None:
    """全局 T0-1 快照 · 供 scanner 注入 macro。"""
    import os

    from apps.copilot.modules.radar.t0_cache import DEFAULT_CACHE_DIR

    base = Path(os.environ.get("RADAR_T0_CACHE_DIR", str(DEFAULT_CACHE_DIR)))
    path = base / "_global" / "market_sentiment.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("global macro cache written status=%s", payload.get("status"))


def read_global_macro_cache() -> dict[str, Any] | None:
    import os

    from apps.copilot.modules.radar.t0_cache import DEFAULT_CACHE_DIR

    base = Path(os.environ.get("RADAR_T0_CACHE_DIR", str(DEFAULT_CACHE_DIR)))
    path = base / "_global" / "market_sentiment.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_global_spot_cache(payload: dict[str, Any]) -> None:
    """全 A 快照行 · 供 T0-7 同业过滤（与 T0-1 同次采集）。"""
    import os

    from apps.copilot.modules.radar.t0_cache import DEFAULT_CACHE_DIR

    if payload.get("status") != "ok":
        return
    rows = payload.get("rows")
    if not rows:
        return
    base = Path(os.environ.get("RADAR_T0_CACHE_DIR", str(DEFAULT_CACHE_DIR)))
    path = base / "_global" / "a_spot_snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    slim = {
        "status": "ok",
        "source": payload.get("source"),
        "trade_date": payload.get("trade_date"),
        "row_count": len(rows),
        "collected_at": payload.get("collected_at"),
        "rows": rows,
    }
    path.write_text(json.dumps(slim, ensure_ascii=False), encoding="utf-8")
    logger.info("global spot cache written rows=%s", len(rows))


def read_global_spot_cache(*, max_age_hours: float = 36.0) -> dict[str, Any] | None:
    import os
    from datetime import datetime, timezone

    from apps.copilot.modules.radar.t0_cache import DEFAULT_CACHE_DIR

    base = Path(os.environ.get("RADAR_T0_CACHE_DIR", str(DEFAULT_CACHE_DIR)))
    path = base / "_global" / "a_spot_snapshot.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ts = data.get("collected_at")
    if ts and max_age_hours > 0:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600
            if age_h > max_age_hours:
                return None
        except ValueError:
            pass
    return data
