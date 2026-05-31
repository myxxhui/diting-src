"""雷达 T0/T2 本地/生产缓存 — 持仓 SoT 预拉 + 扫描读缓存。

A 路径：Mac `make radar-t0-prefetch-with-t2` → 含 t2_verdict 的 bundle JSON
        → `make radar-t0-sync` → copilot PVC `/data/radar_t0_cache/`
B 路径：缓存 miss 时生产 pod 经 HTTPS_PROXY 调 Opus（见 diting-infra/scripts/anthropic-proxy-vps-setup.md）

[Ref: step_14 §3.5 · 21_行情数据源 · 持仓 SoT]
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/cache/radar_t0")
MANIFEST_NAME = "manifest.json"
T0_KEYS = ("quote", "profile", "financials", "valuation")


def cache_dir() -> Path:
    raw = os.getenv("RADAR_T0_CACHE_DIR", "").strip()
    return Path(raw) if raw else DEFAULT_CACHE_DIR


def max_age_hours() -> float:
    try:
        return float(os.getenv("RADAR_T0_CACHE_MAX_AGE_HOURS", "24"))
    except ValueError:
        return 24.0


def cache_path(symbol: str) -> Path:
    sym = symbol.zfill(6)[-6:]
    return cache_dir() / f"{sym}.json"


def cache_enabled() -> bool:
    return os.getenv("RADAR_T0_CACHE_DISABLED", "").lower() not in ("1", "true", "yes")


def live_fallback_enabled() -> bool:
    """生产默认 false：ECS 不 live 拉东财，只读缓存；本机预拉时不影响。"""
    return os.getenv("RADAR_T0_LIVE_FALLBACK", "true").lower() in ("1", "true", "yes")


def _parse_collected_at(bundle: dict[str, Any]) -> datetime | None:
    raw = bundle.get("collected_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def is_fresh(bundle: dict[str, Any], *, max_h: float | None = None) -> bool:
    collected = _parse_collected_at(bundle)
    if collected is None:
        return False
    limit = max_h if max_h is not None else max_age_hours()
    now = datetime.now(timezone.utc)
    delta_h = (now - collected.astimezone(timezone.utc)).total_seconds() / 3600.0
    return delta_h <= limit


def load_cached(symbol: str, *, require_fresh: bool = True) -> dict[str, Any] | None:
    """读单标的 bundle（含 T0 四源 + 可选 t1_distilled / t2_verdict）。"""
    path = cache_path(symbol)
    if not path.is_file():
        return None
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("雷达缓存读取失败 %s: %s", path, exc)
        return None
    if require_fresh and not is_fresh(bundle):
        logger.info("雷达缓存过期 symbol=%s path=%s", symbol, path)
        return None
    return bundle


def cached_t2_verdict(bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    """缓存内 T2 可用且 9 维齐 → 返回 t2_verdict（供 pipeline 跳过 live Opus）。"""
    if not bundle or not is_fresh(bundle):
        return None
    t2 = bundle.get("t2_verdict")
    if not isinstance(t2, dict) or t2.get("status") != "ok":
        return None
    dims = (t2.get("deep_analysis") or {}).get("dimensions") or {}
    if len(dims) < 9:
        return None
    return {**t2, "cache_hit": True, "route": t2.get("route") or "cache"}


def save_cache(bundle: dict[str, Any]) -> Path:
    """写入单标的 bundle JSON（原子写）。"""
    sym = str(bundle.get("symbol", "")).zfill(6)[-6:]
    if not sym:
        raise ValueError("bundle 缺少 symbol")
    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = cache_path(sym)
    tmp = path.with_suffix(".json.tmp")
    payload = {**bundle, "symbol": sym}
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def write_manifest(entries: list[dict[str, Any]]) -> Path:
    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cache_dir": str(root.resolve()),
        "max_age_hours": max_age_hours(),
        "symbol_count": len(entries),
        "entries": entries,
    }
    path = root / MANIFEST_NAME
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def status_summary() -> dict[str, Any]:
    root = cache_dir()
    if not root.is_dir():
        return {"cache_dir": str(root), "exists": False, "symbols": []}
    entries: list[dict[str, Any]] = []
    for p in sorted(root.glob("*.json")):
        if p.name == MANIFEST_NAME:
            continue
        sym = p.stem
        try:
            bundle = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            entries.append({"symbol": sym, "ok": False, "detail": "json 损坏"})
            continue
        ok_parts = sum(
            1 for k in T0_KEYS if (bundle.get(k) or {}).get("status") == "ok"
        )
        t2 = bundle.get("t2_verdict") or {}
        dims = (t2.get("deep_analysis") or {}).get("dimensions") or {}
        entries.append(
            {
                "symbol": sym,
                "name": bundle.get("name"),
                "collected_at": bundle.get("collected_at"),
                "fresh": is_fresh(bundle),
                "ok_parts": ok_parts,
                "t2_status": t2.get("status"),
                "t2_dims": len(dims),
                "t2_cost_yuan": t2.get("cost_yuan"),
                "source": bundle.get("source"),
            }
        )
    return {
        "cache_dir": str(root.resolve()),
        "exists": True,
        "max_age_hours": max_age_hours(),
        "symbol_count": len(entries),
        "fresh_count": sum(1 for e in entries if e.get("fresh")),
        "t2_ok_count": sum(1 for e in entries if e.get("t2_status") == "ok"),
        "symbols": entries,
    }
