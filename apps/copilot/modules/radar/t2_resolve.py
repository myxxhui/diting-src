"""T2 研报解析与回退：live Opus 失败时复用历史 ok 缓存，禁止 error 覆盖 ok。

[Ref: no-mock · 香港 ECS 403 · radar-t0-sync]
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import RadarSymbolVersion
from apps.copilot.modules.radar.t0_cache import (
    _parse_collected_at,
    _read_json,
    cache_path,
    load_cached,
    version_dir,
)

logger = logging.getLogger(__name__)


def ok_t2_from_bundle(bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    """从 bundle 提取 status=ok 且 9 维齐全的 t2_verdict。"""
    if not bundle:
        return None
    t2 = bundle.get("t2_verdict")
    if not isinstance(t2, dict) or t2.get("status") != "ok":
        return None
    dims = (t2.get("deep_analysis") or {}).get("dimensions") or {}
    if len(dims) < 9:
        return None
    return {
        **t2,
        "cache_hit": True,
        "route": t2.get("route") or "cache",
        "stale_fallback": True,
    }


def _bundle_collected_at(bundle: dict[str, Any]) -> datetime | None:
    return _parse_collected_at(bundle)


def _pick_newest_ok_t2(bundles: list[dict[str, Any]]) -> dict[str, Any] | None:
    best_t2: dict[str, Any] | None = None
    best_at: datetime | None = None
    for bundle in bundles:
        t2 = ok_t2_from_bundle(bundle)
        if not t2:
            continue
        collected = _bundle_collected_at(bundle)
        if collected is None:
            if best_t2 is None:
                best_t2 = t2
            continue
        if best_at is None or collected > best_at:
            best_at = collected
            best_t2 = t2
    return best_t2


def iter_file_bundles(symbol: str) -> list[dict[str, Any]]:
    """收集 latest 指针 + versions 目录下全部 bundle（去重 version_id）。"""
    sym = symbol.zfill(6)[-6:]
    by_vid: dict[str, dict[str, Any]] = {}
    latest = load_cached(sym, require_fresh=False)
    if latest:
        vid = str(latest.get("version_id") or "latest")
        by_vid[vid] = latest
    vroot = version_dir(sym)
    if vroot.is_dir():
        for path in vroot.glob("*.json"):
            bundle = _read_json(path)
            if bundle:
                by_vid[str(bundle.get("version_id") or path.stem)] = bundle
    pointer = _read_json(cache_path(sym))
    if pointer:
        vid = str(pointer.get("version_id") or "pointer")
        by_vid[vid] = pointer
    return list(by_vid.values())


def find_ok_t2_verdict(symbol: str) -> dict[str, Any] | None:
    """在文件缓存中找最新一条 ok T2（不要求 T0 新鲜）。"""
    return _pick_newest_ok_t2(iter_file_bundles(symbol))


async def find_ok_t2_verdict_db(
    session: AsyncSession,
    symbol: str,
) -> dict[str, Any] | None:
    """在 DB 全部版本中找最新 ok T2。"""
    sym = symbol.zfill(6)[-6:]
    rows = await session.scalars(
        select(RadarSymbolVersion)
        .where(RadarSymbolVersion.symbol == sym)
        .order_by(RadarSymbolVersion.collected_at.desc(), RadarSymbolVersion.id.desc())
        .limit(20)
    )
    bundles = [r.bundle_json for r in rows if isinstance(r.bundle_json, dict)]
    return _pick_newest_ok_t2(bundles)


async def resolve_ok_t2_verdict(
    session: AsyncSession | None,
    symbol: str,
) -> dict[str, Any] | None:
    """文件 + DB 合并取最新 ok T2。"""
    file_t2 = find_ok_t2_verdict(symbol)
    db_t2 = None
    if session is not None:
        db_t2 = await find_ok_t2_verdict_db(session, symbol)
    if file_t2 and db_t2:
        # 无法精确比较时优先文件（通常为本机 sync 的完整 9 维）
        return file_t2
    return file_t2 or db_t2


def merge_bundle_preserve_ok_t2(bundle: dict[str, Any]) -> dict[str, Any]:
    """save 前：新 t2 非 ok 时不覆盖磁盘上已有的 ok t2。"""
    new_t2 = bundle.get("t2_verdict") or {}
    if new_t2.get("status") == "ok" and len(
        (new_t2.get("deep_analysis") or {}).get("dimensions") or {}
    ) >= 9:
        return bundle
    sym = str(bundle.get("symbol") or "")
    prior = find_ok_t2_verdict(sym)
    if prior:
        logger.info("保留历史 ok T2，拒绝 error 覆盖 symbol=%s", sym)
        bundle = {**bundle, "t2_verdict": prior}
    return bundle


def hydrate_candidate_t2(c: dict[str, Any], t2: dict[str, Any], *, note: str) -> dict[str, Any]:
    """用 ok T2 填充候选展示字段。"""
    deep = t2.get("deep_analysis") or {}
    overall = deep.get("overall") or {}
    out = dict(c)
    out["deep_analysis"] = deep
    out["t2_status"] = "ok"
    out["t2_detail"] = note
    out["t2_from_stale_cache"] = True
    conf = overall.get("confidence")
    if conf is not None:
        out["confidence"] = float(conf)
    cost = out.get("cost") or {}
    if t2.get("cost_yuan") is not None:
        cost = {
            **cost,
            "cost_yuan": t2.get("cost_yuan"),
            "tokens_in": t2.get("tokens_in", 0),
            "tokens_out": t2.get("tokens_out", 0),
            "model": t2.get("model_id"),
            "route": t2.get("route"),
        }
        out["cost"] = cost
    return out


async def hydrate_candidate_for_display(
    session: AsyncSession | None,
    c: dict[str, Any],
) -> dict[str, Any]:
    """DB/文件里存了 error 时，展示层回退到历史 ok（no-mock）。"""
    deep = c.get("deep_analysis") or {}
    dims = deep.get("dimensions") or {}
    if c.get("t2_status") == "ok" and len(dims) >= 9:
        return c
    sym = c.get("symbol") or ""
    if not sym:
        return c
    t2 = await resolve_ok_t2_verdict(session, sym)
    if not t2:
        detail = c.get("t2_detail") or ""
        if "403" in detail or "forbidden" in detail.lower():
            c = dict(c)
            c["t2_detail"] = (
                f"{detail} · 本机可执行：make radar-t0-prefetch-with-t2 后 "
                f"diting-infra make radar-t0-sync；生产 live 需 HTTPS_PROXY"
            )
        return c
    return hydrate_candidate_t2(
        c,
        t2,
        note="展示已回退至历史 Opus 缓存（本次 live 未成功，非编造）",
    )


def classify_opus_failure(detail: str) -> str:
    """403 / 无缓存 / 预算 等分类，供前端文案。"""
    d = (detail or "").lower()
    if "403" in d or "forbidden" in d or "not allowed" in d:
        return "opus_403"
    if "预算" in detail or "budget" in d:
        return "budget"
    return "other"
