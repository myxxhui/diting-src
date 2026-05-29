"""新闻适配器：cryo_guard 公告库（禁止 stub 假新闻顶替）。

启动期 P2 优先读 D1 已采集的 ``announcements``（巨潮）；7 日窗口内无公告时
``total_count_7d=0`` 为预期（非披露季空窗）。

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import feedparser  # type: ignore

    _FEED_OK = True
except Exception:
    feedparser = None  # type: ignore
    _FEED_OK = False


@dataclass
class NewsItem:
    title: str
    summary: str
    source: str
    publish_time: datetime
    url: str = ""
    sentiment: float = 0.0
    event_type: str = "neutral"


_POS_WORDS = {"超预期", "增长", "利好", "突破", "新高", "盈利", "扭亏"}
_NEG_WORDS = {"下滑", "暴雷", "处罚", "诉讼", "减持", "亏损", "暴跌", "退市"}


def _simple_sentiment(text: str) -> float:
    pos = sum(1 for w in _POS_WORDS if w in text)
    neg = sum(1 for w in _NEG_WORDS if w in text)
    if pos == 0 and neg == 0:
        return 0.0
    return (pos - neg) / max(pos + neg, 1)


def _cryo_db_path() -> Path:
    env = os.environ.get("CRYO_DB_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[4] / "data" / "cryo_guard.db"


def _fetch_from_cryo_db(symbol: str, days: int) -> list[NewsItem]:
    db = _cryo_db_path()
    if not db.is_file():
        return []
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    try:
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            """
            SELECT title, content, ann_type, ann_date, url, source
            FROM announcements
            WHERE symbol = ? AND ann_date >= ?
            ORDER BY ann_date DESC
            LIMIT 50
            """,
            (symbol, cutoff),
        ).fetchall()
        conn.close()
    except Exception as exc:
        logger.warning("cryo announcements 读取失败 symbol=%s err=%s", symbol, exc)
        return []

    items: list[NewsItem] = []
    for title, content, ann_type, ann_date, url, source in rows:
        summary = (content or "")[:500]
        pub = datetime.strptime(str(ann_date), "%Y-%m-%d")
        items.append(
            NewsItem(
                title=str(title),
                summary=summary or str(ann_type or ""),
                source=str(source or "cninfo"),
                publish_time=pub,
                url=str(url or ""),
            )
        )
    return items


def fetch_recent_news(symbol: str, days: int = 7) -> list[NewsItem]:
    items = _fetch_from_cryo_db(symbol, days)
    cutoff = datetime.utcnow() - timedelta(days=days)
    items = [n for n in items if n.publish_time >= cutoff]
    for n in items:
        text = f"{n.title} {n.summary}"
        if n.sentiment == 0:
            n.sentiment = _simple_sentiment(text)
        if n.event_type == "neutral":
            if n.sentiment > 0.2:
                n.event_type = "positive"
            elif n.sentiment < -0.2:
                n.event_type = "negative"
    if _FEED_OK and feedparser is not None and not items:
        logger.debug("news 7d 空窗 symbol=%s（cryo DB 无近 %dd 条目）", symbol, days)
    return items
