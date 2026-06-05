"""T0-1 日级历史补录（近 N 交易日 · 交易所成交额 + 涨跌比）。

实时 push2delay 仅当前断面；历史靠 PG 按日累积。本模块在 PG 缺口时用：
- 上交所 + 深交所日成交概况 → ``total_turnover_yi``（口径 ``exchange:sse_szse``）
- 乐咕乐股 ``stock_market_activity_legu`` → 仅**当日**可采 ``advance_ratio``

[Ref: 27_ §2.2.1]
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

SOURCE_EXCHANGE = "exchange:sse_szse_backfill"
SOURCE_LEGU_TODAY = "legulegu:market_activity"


def _today_cn() -> date:
    return datetime.now(timezone(timedelta(hours=8))).date()


def recent_trade_dates(*, days: int = 7, before: date | None = None) -> list[date]:
    """最近 N 个 A 股交易日（含 before 当日；默认含今天）。"""
    import akshare as ak

    end = before or _today_cn()
    cal = ak.tool_trade_date_hist_sina()
    cal["trade_date"] = cal["trade_date"].astype(str)
    eligible = cal[cal["trade_date"] <= end.isoformat()]
    out = [date.fromisoformat(str(x)[:10]) for x in eligible["trade_date"].tolist()]
    return out[-days:]


def fetch_exchange_turnover_yi(trade_date: date) -> float | None:
    """沪深两市股票成交额合计（亿元）· 交易所日概况。"""
    import akshare as ak

    d = trade_date.strftime("%Y%m%d")
    try:
        sz = ak.stock_szse_summary(date=d)
    except Exception as exc:  # noqa: BLE001
        logger.warning("深交所日概况拉取失败 %s: %s", d, exc)
        return None

    sse_yi: float | None = None
    try:
        sse = ak.stock_sse_deal_daily(date=d)
        sse_yi = float(sse.loc[sse["单日情况"] == "成交金额", "股票"].iloc[0])
    except Exception as exc:  # noqa: BLE001
        # 盘中未收盘时 akshare 解析可能失败；用主板A+科创板+主板B 近似
        logger.warning("上交所成交金额主路径失败 %s: %s · 尝试分项加总", d, exc)
        try:
            sse = ak.stock_sse_deal_daily(date=d)
            row = sse.loc[sse["单日情况"] == "成交金额"]
            parts = []
            for col in ("主板A", "科创板", "主板B", "股票"):
                if col in row.columns:
                    try:
                        parts.append(float(row[col].iloc[0]))
                    except (TypeError, ValueError):
                        pass
            sse_yi = round(sum(parts), 2) if parts else None
        except Exception as exc2:  # noqa: BLE001
            logger.warning("上交所成交金额分项加总失败 %s: %s", d, exc2)
            sse_yi = None

    if sse_yi is None:
        return None

    try:
        stock_row = sz.loc[sz["证券类别"].astype(str).str.fullmatch("股票")]
        if stock_row.empty:
            stock_row = sz.loc[sz["证券类别"].astype(str).str.contains("股票", na=False)]
        sz_yuan = float(stock_row["成交金额"].iloc[0])
        sz_yi = sz_yuan / 1e8
    except (IndexError, KeyError, TypeError, ValueError):
        logger.warning("深交所成交金额解析失败 %s", d)
        return None

    return round(sse_yi + sz_yi, 2)


def fetch_legu_advance_ratio(trade_date: date) -> dict[str, Any] | None:
    """乐咕乐股当日涨跌家数 → advance_ratio（仅 trade_date=今日有效）。"""
    if trade_date != _today_cn():
        return None
    try:
        import akshare as ak

        df = ak.stock_market_activity_legu()
    except Exception as exc:  # noqa: BLE001
        logger.warning("legulegu market_activity 失败: %s", exc)
        return None

    kv = dict(zip(df["item"].astype(str), df["value"]))
    try:
        up = float(kv.get("上涨") or 0)
        down = float(kv.get("下跌") or 0)
        flat = float(kv.get("平盘") or 0)
    except (TypeError, ValueError):
        return None
    denom = up + down + flat
    if denom <= 0:
        return None
    try:
        limit_up = int(float(kv.get("涨停") or 0))
    except (TypeError, ValueError):
        limit_up = None
    return {
        "advance_ratio": round(up / denom, 4),
        "advance_count": int(up),
        "total_count": int(denom),
        "limit_up_height": limit_up,
        "legu_meta": {k: kv.get(k) for k in ("上涨", "下跌", "平盘", "涨停", "跌停", "统计日期")},
    }


def build_backfill_payload(trade_date: date) -> dict[str, Any] | None:
    """单日补录 payload；失败返回 None。"""
    turnover = fetch_exchange_turnover_yi(trade_date)
    if turnover is None:
        return None

    legu = fetch_legu_advance_ratio(trade_date) or {}
    source = SOURCE_LEGU_TODAY if legu else SOURCE_EXCHANGE
    payload: dict[str, Any] = {
        "status": "ok",
        "trade_date": trade_date.isoformat(),
        "total_turnover_yi": turnover,
        "exchange_turnover_yi": turnover,
        "turnover_vs_prev_pct": None,
        "advance_ratio": legu.get("advance_ratio"),
        "advance_count": legu.get("advance_count"),
        "total_count": legu.get("total_count"),
        "limit_up_height": legu.get("limit_up_height"),
        "finalized": True,
        "source": source,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "backfill": True,
    }
    if legu.get("legu_meta"):
        payload["legu_meta"] = legu["legu_meta"]
    return payload


def apply_turnover_vs_prev_chain(rows: list[dict[str, Any]]) -> None:
    """按 trade_date 升序写 turnover_vs_prev_pct（同比口径：exchange_turnover_yi 优先）。"""
    rows.sort(key=lambda r: r.get("trade_date") or "")
    prev_turnover: float | None = None
    for row in rows:
        today = row.get("exchange_turnover_yi") or row.get("total_turnover_yi")
        if today is None or prev_turnover in (None, 0):
            row["turnover_vs_prev_pct"] = None
        else:
            try:
                row["turnover_vs_prev_pct"] = round(
                    (float(today) - float(prev_turnover)) / float(prev_turnover) * 100,
                    2,
                )
            except (TypeError, ValueError):
                row["turnover_vs_prev_pct"] = None
        if today is not None:
            prev_turnover = float(today)


async def backfill_sentiment_daily(
    session: Any,
    *,
    days: int = 7,
    overwrite: bool = False,
) -> dict[str, Any]:
    """补录近 N 交易日至 ``radar_market_sentiment_daily``。"""
    from sqlalchemy import select

    from apps.copilot.db.models import RadarMarketSentimentDaily
    from apps.copilot.modules.radar.t0.collectors.market_sentiment import upsert_sentiment_pg

    targets = recent_trade_dates(days=days)
    inserted = 0
    skipped = 0
    errors: list[str] = []

    for td in targets:
        existing = await session.get(RadarMarketSentimentDaily, td)
        if existing is not None and not overwrite:
            skipped += 1
            continue

        payload = await asyncio.to_thread(build_backfill_payload, td)
        if not payload:
            errors.append(f"{td}: 补录拉取失败")
            continue

        await upsert_sentiment_pg(session, payload)
        inserted += 1

    await session.flush()

    # 重算全表环比（exchange_turnover_yi 统一口径）
    q = select(RadarMarketSentimentDaily).order_by(RadarMarketSentimentDaily.trade_date.asc())
    db_rows = list((await session.scalars(q)).all())
    chain_payloads: list[dict[str, Any]] = []
    for row in db_rows:
        snap = dict(row.snapshot_json or {})
        snap["trade_date"] = row.trade_date.isoformat()
        snap["total_turnover_yi"] = row.total_turnover_yi
        ex = snap.get("exchange_turnover_yi")
        if ex is None:
            ex = await asyncio.to_thread(fetch_exchange_turnover_yi, row.trade_date)
            if ex is not None:
                snap["exchange_turnover_yi"] = ex
        snap["exchange_turnover_yi"] = snap.get("exchange_turnover_yi") or row.total_turnover_yi
        snap["advance_ratio"] = row.advance_ratio
        chain_payloads.append(snap)

    apply_turnover_vs_prev_chain(chain_payloads)
    by_date = {p["trade_date"]: p for p in chain_payloads}
    for row in db_rows:
        patched = by_date.get(row.trade_date.isoformat())
        if not patched:
            continue
        row.turnover_vs_prev_pct = patched.get("turnover_vs_prev_pct")
        sj = dict(row.snapshot_json or {})
        sj["turnover_vs_prev_pct"] = patched.get("turnover_vs_prev_pct")
        if patched.get("exchange_turnover_yi") is not None:
            sj["exchange_turnover_yi"] = patched.get("exchange_turnover_yi")
        row.snapshot_json = sj

    return {
        "job_id": "sentiment-backfill",
        "status": "ok" if not errors else "partial",
        "targets": [d.isoformat() for d in targets],
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
        "pg_rows": len(db_rows),
    }
