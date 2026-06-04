"""T0-7 同业排名 · 读全局 spot 缓存。

[Ref: 27_ T0-7]
"""
from __future__ import annotations

from typing import Any


def collect_peer_rank(sym: str, *, industry: str | None = None) -> dict[str, Any]:
    from apps.copilot.modules.radar.scanner import _collect_profile
    from apps.copilot.modules.radar.t0.jobs.cache_merge import read_global_spot_cache

    sym = str(sym).zfill(6)[-6:]
    prof = _collect_profile(sym)
    mv_self = prof.get("total_mv_yi") if prof.get("status") == "ok" else None

    spot = read_global_spot_cache()
    rows = (spot or {}).get("rows") or []
    if not rows:
        return {
            "status": "error",
            "detail": "T0-7 同业排名未获取（全 A 快照缓存不可用 · 须 sentiment Cron 先成功）",
        }

    spot_ind = None
    for row in rows:
        if str(row.get("code") or "").zfill(6)[-6:] == sym:
            spot_ind = row.get("industry")
            break
    ind = (spot_ind or industry or prof.get("industry") or "").strip()
    if not ind or mv_self is None:
        return {"status": "skip", "detail": "缺行业或市值，无法同业排名"}

    peers: list[tuple[str, float]] = []
    for row in rows:
        if str(row.get("industry") or "").strip() != ind:
            continue
        code = str(row.get("code") or "").zfill(6)[-6:]
        try:
            mv_raw = float(row.get("total_mv") or 0)
            mv = mv_raw / 1e8 if mv_raw > 1e6 else mv_raw
        except (TypeError, ValueError):
            mv = 0.0
        if code == sym and mv <= 0 and mv_self:
            mv = float(mv_self)
        if mv > 0:
            peers.append((code, mv))

    if not peers:
        return {"status": "error", "detail": f"T0-7 行业 {ind} 无同业样本"}

    peers.sort(key=lambda x: x[1], reverse=True)
    rank = next((i for i, (code, _mv) in enumerate(peers, start=1) if code == sym), None)
    if rank is None:
        return {"status": "error", "detail": "T0-7 标的未出现在同业快照"}

    return {
        "status": "ok",
        "source": "eastmoney:push2delay/spot_cache",
        "industry": ind,
        "industry_spot": spot_ind,
        "rank": rank,
        "peer_count": len(peers),
        "total_mv_yi": mv_self,
    }
