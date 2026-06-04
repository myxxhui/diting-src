"""雷达 bundle 数据库持久化：文件缓存 24h · DB 30 天 · 每标的 7 版。

[Ref: 24_需求实现表 · 波次四]
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import RadarSymbolVersion
from apps.copilot.modules.radar.t0_cache import (
    T0_KEYS,
    _parse_collected_at,
    _version_summary,
    is_fresh,
    list_versions as list_file_versions,
    load_version as load_file_version,
)

logger = logging.getLogger(__name__)


def file_retention_hours() -> float:
    raw = os.getenv("RADAR_FILE_RETENTION_HOURS", "24").strip()
    try:
        return float(raw)
    except ValueError:
        return 24.0


def db_retention_days() -> float:
    from apps.copilot.modules.radar.workbench_prefs import effective_float

    return effective_float("db_retention_days", "RADAR_DB_RETENTION_DAYS", 30.0)


def max_versions_per_symbol() -> int:
    from apps.copilot.modules.radar.workbench_prefs import effective_float

    try:
        return max(1, int(effective_float("max_versions_per_symbol", "RADAR_DB_MAX_VERSIONS", 7)))
    except ValueError:
        return 7


def recent_analysis_days() -> float:
    from apps.copilot.modules.radar.workbench_prefs import effective_float

    return effective_float("recent_analysis_days", "RADAR_RECENT_ANALYSIS_DAYS", 7.0)


def _bundle_stats(bundle: dict[str, Any]) -> tuple[int, str | None, float | None]:
    ok = sum(1 for k in T0_KEYS if (bundle.get(k) or {}).get("status") == "ok")
    t2 = bundle.get("t2_verdict") or {}
    cost = t2.get("cost_yuan")
    if cost is None and isinstance(t2.get("cost"), dict):
        cost = t2["cost"].get("yuan")
    return ok, t2.get("status"), float(cost) if cost is not None else None


async def sync_bundle_to_db(session: AsyncSession, bundle: dict[str, Any]) -> str:
    """将 bundle  upsert 到 radar_symbol_versions 并修剪旧版。"""
    sym = str(bundle.get("symbol", "")).zfill(6)[-6:]
    if not sym:
        raise ValueError("bundle 缺少 symbol")
    version_id = str(bundle.get("version_id") or "")
    if not version_id:
        from apps.copilot.modules.radar.t0_cache import make_version_id

        collected = _parse_collected_at(bundle) or datetime.now(timezone.utc)
        version_id = make_version_id(collected)

    ok_parts, t2_status, cost_yuan = _bundle_stats(bundle)
    collected = _parse_collected_at(bundle)

    existing = await session.scalar(
        select(RadarSymbolVersion).where(
            RadarSymbolVersion.symbol == sym,
            RadarSymbolVersion.version_id == version_id,
        )
    )
    if existing:
        existing.bundle_json = bundle
        existing.name = str(bundle.get("name") or existing.name or sym)
        existing.collected_at = collected
        existing.source = bundle.get("source")
        existing.t0_ok_parts = ok_parts
        existing.t2_status = t2_status
        existing.cost_yuan = cost_yuan
    else:
        session.add(
            RadarSymbolVersion(
                symbol=sym,
                version_id=version_id,
                name=str(bundle.get("name") or sym),
                collected_at=collected,
                source=bundle.get("source"),
                bundle_json=bundle,
                t0_ok_parts=ok_parts,
                t2_status=t2_status,
                cost_yuan=cost_yuan,
            )
        )
    await session.flush()
    await _prune_symbol_versions(session, sym)
    await _prune_expired_db(session)
    return version_id


async def _prune_symbol_versions(session: AsyncSession, symbol: str) -> None:
    limit = max_versions_per_symbol()
    rows = await session.scalars(
        select(RadarSymbolVersion)
        .where(RadarSymbolVersion.symbol == symbol)
        .order_by(RadarSymbolVersion.collected_at.desc(), RadarSymbolVersion.id.desc())
    )
    all_rows = list(rows)
    for row in all_rows[limit:]:
        await session.delete(row)


async def _prune_expired_db(session: AsyncSession) -> None:
    # SQLite DateTime 存 naive UTC；勿用 offset-aware 比较（会 TypeError）
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=db_retention_days())
    ).replace(tzinfo=None)
    await session.execute(
        delete(RadarSymbolVersion).where(RadarSymbolVersion.synced_at < cutoff)
    )


async def load_bundle_db(
    session: AsyncSession,
    symbol: str,
    version_id: str,
) -> dict[str, Any] | None:
    sym = symbol.zfill(6)[-6:]
    row = await session.scalar(
        select(RadarSymbolVersion).where(
            RadarSymbolVersion.symbol == sym,
            RadarSymbolVersion.version_id == version_id,
        )
    )
    if row and isinstance(row.bundle_json, dict):
        return row.bundle_json
    return None


async def load_latest_bundle_db(
    session: AsyncSession,
    symbol: str,
    *,
    max_age_hours: float | None = None,
) -> dict[str, Any] | None:
    sym = symbol.zfill(6)[-6:]
    row = await session.scalar(
        select(RadarSymbolVersion)
        .where(RadarSymbolVersion.symbol == sym)
        .order_by(RadarSymbolVersion.collected_at.desc(), RadarSymbolVersion.id.desc())
        .limit(1)
    )
    if not row or not isinstance(row.bundle_json, dict):
        return None
    bundle = row.bundle_json
    if max_age_hours is not None:
        collected = _parse_collected_at(bundle)
        if collected is None:
            return None
        age_h = (
            datetime.now(timezone.utc) - collected.astimezone(timezone.utc)
        ).total_seconds() / 3600.0
        if age_h > max_age_hours:
            return None
    return bundle


async def list_versions_db(session: AsyncSession, symbol: str) -> list[dict[str, Any]]:
    sym = symbol.zfill(6)[-6:]
    cutoff = datetime.now(timezone.utc) - timedelta(days=db_retention_days())
    rows = await session.scalars(
        select(RadarSymbolVersion)
        .where(RadarSymbolVersion.symbol == sym)
        .order_by(RadarSymbolVersion.collected_at.desc(), RadarSymbolVersion.id.desc())
        .limit(max_versions_per_symbol() * 2)
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        bundle = row.bundle_json if isinstance(row.bundle_json, dict) else {}
        collected = row.collected_at or _parse_collected_at(bundle)
        if collected and collected.replace(tzinfo=timezone.utc) < cutoff:
            continue
        summary = _version_summary(bundle, row.version_id, is_latest=len(out) == 0)
        summary["storage"] = "db"
        summary["synced_at"] = row.synced_at.isoformat() if row.synced_at else None
        out.append(summary)
        if len(out) >= max_versions_per_symbol():
            break
    return out


async def list_versions_merged(
    session: AsyncSession,
    symbol: str,
) -> list[dict[str, Any]]:
    """审计用：DB 为主，文件缓存补充（去重 version_id）。"""
    sym = symbol.zfill(6)[-6:]
    by_id: dict[str, dict[str, Any]] = {}
    for v in await list_versions_db(session, sym):
        by_id[v["version_id"]] = v
    file_days = max(db_retention_days(), file_retention_hours() / 24.0)
    for v in list_file_versions(sym, days=file_days):
        vid = v.get("version_id")
        if vid and vid not in by_id:
            v["storage"] = "file"
            by_id[vid] = v
    merged = sorted(
        by_id.values(),
        key=lambda x: x.get("collected_at") or "",
        reverse=True,
    )
    return merged[: max_versions_per_symbol()]


async def load_version_merged(
    session: AsyncSession,
    symbol: str,
    version_id: str,
) -> dict[str, Any] | None:
    bundle = load_file_version(symbol, version_id)
    if bundle:
        return bundle
    return await load_bundle_db(session, symbol, version_id)


async def symbol_data_status(
    session: AsyncSession,
    symbol: str,
) -> dict[str, Any]:
    sym = symbol.zfill(6)[-6:]
    versions = await list_versions_merged(session, sym)
    latest = versions[0] if versions else None
    file_bundle = load_file_version(sym, latest["version_id"]) if latest else None
    if not file_bundle and latest:
        file_bundle = await load_bundle_db(session, sym, latest["version_id"])
    fresh_file = is_fresh(file_bundle) if file_bundle else False
    return {
        "symbol": sym,
        "version_count": len(versions),
        "versions": versions,
        "latest": latest,
        "file_cache_fresh": fresh_file,
        "file_retention_hours": file_retention_hours(),
        "db_retention_days": db_retention_days(),
        "max_versions": max_versions_per_symbol(),
    }
