"""互动易 / 投资者问答 · GB200 进度补充。

[Ref: 28_ §2.2 fii_gb200_milestone · T0 Sensor Layer]
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any

from apps.copilot.modules.executing.l3.fii_gb200_milestone.constants import (
    ANNOUNCEMENT_KEYWORDS,
    event_window_meta,
    event_window_start,
    is_within_event_window,
)

_CST = timezone(timedelta(hours=8))
_INTERACT_KW = re.compile(r"互动易|投资者提问|回复|问答", re.I)


def fetch_interactive_e_supplement(symbol: str) -> dict[str, Any]:
    """巨潮 · 互动易/投资者问答摘录（近 12 个月 · 标题优先）。"""
    from apps.cryo_guard.cninfo_client import iter_cninfo_announcements

    sym = symbol.zfill(6)[-6:]
    end = datetime.now(_CST)
    start = event_window_start(ref=end)
    hits: list[dict[str, Any]] = []

    for kw in ("互动易", "投资者关系", "提问", "GB200", "智算"):
        for item in iter_cninfo_announcements(
            sym,
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            keyword=kw,
            max_pages=3,
            throttle_sec=0.15,
        ):
            title = re.sub(r"<[^>]+>", "", str(item.get("announcementTitle") or "")).strip()
            pub = str(item.get("announcementTime") or "")[:10]
            if pub and not is_within_event_window(pub, ref=end):
                continue
            blob = title
            if not _INTERACT_KW.search(blob) and kw in ("互动易", "提问"):
                if not any(k in blob for k in ANNOUNCEMENT_KEYWORDS[:6]):
                    continue
            if not any(k in blob for k in (*ANNOUNCEMENT_KEYWORDS, "互动", "提问", "回复")):
                continue
            hits.append({"title": title, "published_date": pub, "source_kw": kw})

    if not hits:
        return {"ok": False, "blocker": "近12个月无互动易/问答命中"}

    best = max(hits, key=lambda h: (str(h.get("published_date") or ""), len(h.get("title") or "")))
    return {
        "ok": True,
        "source": "cninfo:interactive_e_scan",
        "title": best["title"],
        "published_date": best.get("published_date"),
        "interactive_e_text": best["title"],
        "event_window": event_window_meta(ref=end),
    }
