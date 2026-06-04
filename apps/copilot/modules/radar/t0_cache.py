"""雷达 T0/T1/T2 版本化缓存 — 最近 N 天可审计、latest 指针 + 历史版本目录。

A 路径：Mac `make radar-t0-prefetch-with-t2` → bundle → `make radar-t0-sync`
B 路径：扫描 `force_refresh` → live T0/T2 → 新版本入库

[Ref: step_14 §3.5 · 21_行情数据源 · 持仓 SoT]
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/cache/radar_t0")
MANIFEST_NAME = "manifest.json"
VERSIONS_DIR = "versions"
T0_KEYS = ("quote", "profile", "financials", "valuation")


def cache_dir() -> Path:
    raw = os.getenv("RADAR_T0_CACHE_DIR", "").strip()
    return Path(raw) if raw else DEFAULT_CACHE_DIR


def file_retention_hours() -> float:
    """本地文件缓存保留时长（默认 24h）；与 DB 30 天分离。workbench_prefs 可热覆盖。"""
    from apps.copilot.modules.radar.workbench_prefs import effective_float

    legacy = os.getenv("RADAR_T0_RETENTION_DAYS", "").strip()
    legacy_h = 24.0
    if legacy:
        try:
            legacy_h = float(legacy) * 24.0
        except ValueError:
            pass
    return effective_float("file_cache_hours", "RADAR_FILE_RETENTION_HOURS", legacy_h)


def retention_days() -> float:
    """文件版本目录清理窗口（天）= file_retention_hours / 24。"""
    return file_retention_hours() / 24.0


def max_age_hours() -> float:
    """T0 新鲜度窗口：默认与文件缓存一致（24h）。"""
    raw = os.getenv("RADAR_T0_CACHE_MAX_AGE_HOURS", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return file_retention_hours()


def t2_max_age_hours() -> float:
    """T2 研报可复用窗口（默认 7 天）。workbench_prefs 可热覆盖。"""
    from apps.copilot.modules.radar.workbench_prefs import effective_float

    days_h = effective_float("recent_analysis_days", "RADAR_RECENT_ANALYSIS_DAYS", 7.0) * 24.0
    return effective_float("t2_cache_hours", "RADAR_T2_CACHE_MAX_AGE_HOURS", days_h)


def cache_path(symbol: str) -> Path:
    sym = symbol.zfill(6)[-6:]
    return cache_dir() / f"{sym}.json"


def version_dir(symbol: str) -> Path:
    sym = symbol.zfill(6)[-6:]
    return cache_dir() / VERSIONS_DIR / sym


def make_version_id(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def cache_enabled() -> bool:
    return os.getenv("RADAR_T0_CACHE_DISABLED", "").lower() not in ("1", "true", "yes")


def live_fallback_enabled() -> bool:
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


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("雷达缓存读取失败 %s: %s", path, exc)
        return None


def load_cached(symbol: str, *, require_fresh: bool = True) -> dict[str, Any] | None:
    """读最新 bundle（`{symbol}.json`）。"""
    bundle = _read_json(cache_path(symbol))
    if bundle is None:
        return None
    if require_fresh and not is_fresh(bundle):
        logger.info("雷达缓存过期 symbol=%s", symbol)
        return None
    return bundle


def load_version(symbol: str, version_id: str) -> dict[str, Any] | None:
    """读指定历史版本（7 天保留期内）。"""
    sym = symbol.zfill(6)[-6:]
    vid = (version_id or "").strip()
    if not vid:
        return None
    path = version_dir(sym) / f"{vid}.json"
    bundle = _read_json(path)
    if bundle is not None:
        return bundle
    if vid == "latest":
        return _read_json(cache_path(sym))
    return None


def list_versions(
    symbol: str,
    *,
    days: float | None = None,
) -> list[dict[str, Any]]:
    """列出标的最近 N 天内的缓存版本（新→旧）。"""
    sym = symbol.zfill(6)[-6:]
    window = days if days is not None else retention_days()
    cutoff = datetime.now(timezone.utc) - timedelta(days=window)
    out: list[dict[str, Any]] = []

    vroot = version_dir(sym)
    if vroot.is_dir():
        for p in sorted(vroot.glob("*.json"), reverse=True):
            vid = p.stem
            bundle = _read_json(p)
            if not bundle:
                continue
            collected = _parse_collected_at(bundle)
            if collected and collected < cutoff:
                continue
            out.append(_version_summary(bundle, vid, path=str(p)))

    latest = _read_json(cache_path(sym))
    if latest:
        vid = str(latest.get("version_id") or "latest")
        if not any(x["version_id"] == vid for x in out):
            collected = _parse_collected_at(latest)
            if not collected or collected >= cutoff:
                out.insert(0, _version_summary(latest, vid, path=str(cache_path(sym)), is_latest=True))

    out.sort(key=lambda x: x.get("collected_at") or "", reverse=True)
    return out


def _version_summary(
    bundle: dict[str, Any],
    version_id: str,
    *,
    path: str = "",
    is_latest: bool = False,
) -> dict[str, Any]:
    t2 = bundle.get("t2_verdict") or {}
    dims = (t2.get("deep_analysis") or {}).get("dimensions") or {}
    ok_parts = sum(1 for k in T0_KEYS if (bundle.get(k) or {}).get("status") == "ok")
    return {
        "version_id": version_id,
        "symbol": bundle.get("symbol"),
        "name": bundle.get("name"),
        "collected_at": bundle.get("collected_at"),
        "source": bundle.get("source"),
        "is_latest": is_latest,
        "fresh": is_fresh(bundle),
        "ok_parts": ok_parts,
        "t2_status": t2.get("status"),
        "t2_dims": len(dims),
        "t2_cost_yuan": t2.get("cost_yuan"),
        "path": path,
    }


def cached_t2_verdict(bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    if not bundle or not is_fresh(bundle, max_h=t2_max_age_hours()):
        return None
    t2 = bundle.get("t2_verdict")
    if not isinstance(t2, dict) or t2.get("status") != "ok":
        return None
    dims = (t2.get("deep_analysis") or {}).get("dimensions") or {}
    if len(dims) < 9:
        return None
    return {**t2, "cache_hit": True, "route": t2.get("route") or "cache"}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _prune_old_versions(symbol: str) -> None:
    sym = symbol.zfill(6)[-6:]
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days())
    vroot = version_dir(sym)
    if not vroot.is_dir():
        return
    for p in vroot.glob("*.json"):
        bundle = _read_json(p)
        collected = _parse_collected_at(bundle) if bundle else None
        if collected and collected < cutoff:
            try:
                p.unlink()
            except OSError as exc:
                logger.warning("删除过期版本失败 %s: %s", p, exc)


def save_cache(bundle: dict[str, Any]) -> str:
    """写入最新指针 + 历史版本（保留最近 retention_days 天）。返回 version_id。"""
    from apps.copilot.modules.radar.t2_resolve import merge_bundle_preserve_ok_t2

    bundle = merge_bundle_preserve_ok_t2(bundle)
    sym = str(bundle.get("symbol", "")).zfill(6)[-6:]
    if not sym:
        raise ValueError("bundle 缺少 symbol")

    collected = _parse_collected_at(bundle) or datetime.now(timezone.utc)
    version_id = str(bundle.get("version_id") or make_version_id(collected))
    payload = {
        **bundle,
        "symbol": sym,
        "version_id": version_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }

    _atomic_write_json(cache_path(sym), payload)
    _atomic_write_json(version_dir(sym) / f"{version_id}.json", payload)
    _prune_old_versions(sym)
    bundle["version_id"] = version_id
    return version_id


def build_bundle_from_pipeline(
    pipe: dict[str, Any],
    *,
    source: str = "scan",
) -> dict[str, Any]:
    """从 pipeline 输出组装可版本化的 bundle。"""
    t0 = pipe.get("t0_raw") or {}
    return {
        "symbol": t0.get("symbol"),
        "name": t0.get("name"),
        "collected_at": t0.get("collected_at") or datetime.now(timezone.utc).isoformat(),
        "source": source,
        "quote": t0.get("quote"),
        "profile": t0.get("profile"),
        "financials": t0.get("financials"),
        "valuation": t0.get("valuation"),
        "t1_distilled": pipe.get("t1_distilled"),
        "t2_verdict": pipe.get("t2_verdict"),
    }


def write_manifest(entries: list[dict[str, Any]]) -> Path:
    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cache_dir": str(root.resolve()),
        "max_age_hours": max_age_hours(),
        "retention_days": retention_days(),
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
        versions = list_versions(sym)
        latest = _read_json(p)
        if not latest:
            continue
        entries.append(
            {
                "symbol": sym,
                "name": latest.get("name"),
                "version_count": len(versions),
                "latest_version_id": latest.get("version_id"),
                "collected_at": latest.get("collected_at"),
                "fresh": is_fresh(latest),
                "t2_status": (latest.get("t2_verdict") or {}).get("status"),
            }
        )
    return {
        "cache_dir": str(root.resolve()),
        "exists": True,
        "max_age_hours": max_age_hours(),
        "retention_days": retention_days(),
        "symbol_count": len(entries),
        "symbols": entries,
    }
