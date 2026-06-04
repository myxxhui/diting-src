"""行情数据适配器 — 规约 21：腾讯/新浪 K 线优先，东财 akshare 末级降级.

默认 ``fetch_bars_60d`` 走 ``MarketQuoteClient.get_recent_kline``（腾讯 fqkline → 新浪 K 线）。
仅当 MarketQuote 全源失败时，才降级 ``akshare.stock_zh_a_hist``（东财 push2his）。

真源均失败时返回空列表（禁止随机 stub K 线顶替）。

[Ref: 03_/_共享规约/21_行情数据源降级与断路器规约.md]
[Ref: 03_/03_维度三/.../step_03]
"""
from __future__ import annotations

import concurrent.futures
import logging
import os
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

_AKSHARE_FALLBACK_TIMEOUT = float(os.environ.get("STATE_WATCH_AKSHARE_TIMEOUT_SEC", "8"))


@dataclass
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover_pct: float = 0.0


def _from_market_quote(symbol: str, days: int = 60) -> list[Bar] | None:
    try:
        import os

        from apps.common.market_quote import MarketQuoteClient

        url = os.environ.get("COPILOT_REDIS_URL") or os.environ.get("REDIS_URL")
        client = MarketQuoteClient(redis_url=url) if url else MarketQuoteClient()
        klines = client.get_recent_kline(symbol, days=days)
        if not klines:
            return None
        logger.debug("K线 symbol=%s days=%d source=market_quote rows=%d", symbol, days, len(klines))
        return [
            Bar(
                date=k.date.isoformat() if hasattr(k.date, "isoformat") else str(k.date),
                open=float(k.open),
                high=float(k.high),
                low=float(k.low),
                close=float(k.close),
                volume=float(k.volume),
                turnover_pct=0.0,
            )
            for k in klines
        ]
    except Exception as exc:
        logger.warning("market_quote K线失败 symbol=%s: %s", symbol, exc)
        return None


def _from_akshare_impl(symbol: str, days: int) -> list[Bar] | None:
    try:
        import akshare as ak  # type: ignore
    except Exception:
        return None
    df = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        adjust="qfq",
        end_date=datetime.utcnow().strftime("%Y%m%d"),
    )
    if df is None or df.empty:
        return None
    bars: list[Bar] = []
    for _, row in df.tail(days).iterrows():
        bars.append(
            Bar(
                date=str(row.get("日期", "")),
                open=float(row.get("开盘", 0)),
                high=float(row.get("最高", 0)),
                low=float(row.get("最低", 0)),
                close=float(row.get("收盘", 0)),
                volume=float(row.get("成交量", 0)),
                turnover_pct=float(row.get("换手率", 0) or 0),
            )
        )
    return bars if bars else None


def _from_akshare(symbol: str, days: int = 60) -> list[Bar] | None:
    """东财 push2his 末级降级（akshare 封装）；超时则放弃。"""
    if os.environ.get("STATE_WATCH_QUOTE_AKSHARE_FALLBACK", "1").lower() in ("0", "false", "no"):
        return None
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_from_akshare_impl, symbol, days)
            bars = fut.result(timeout=_AKSHARE_FALLBACK_TIMEOUT)
    except concurrent.futures.TimeoutError:
        logger.warning(
            "akshare K线超时 symbol=%s（%.0fs），跳过东财降级",
            symbol,
            _AKSHARE_FALLBACK_TIMEOUT,
        )
        return None
    except Exception as exc:
        logger.warning("akshare 行情拉取失败 symbol=%s: %s", symbol, exc)
        return None
    if bars:
        logger.info(
            "K线 symbol=%s days=%d source=akshare_eastmoney rows=%d（腾讯/新浪不可用后的降级）",
            symbol,
            days,
            len(bars),
        )
    return bars


def fetch_bars_60d(symbol: str) -> list[Bar]:
    return fetch_bars(symbol, 60)


def fetch_bars(symbol: str, days: int = 60) -> list[Bar]:
    """近 N 日 K 线（腾讯/新浪 → 东财 akshare 降级）。"""
    bars = _from_market_quote(symbol, days)
    if bars:
        return bars
    bars = _from_akshare(symbol, days)
    if bars:
        return bars
    logger.warning(
        "行情不可用 symbol=%s days=%d（MarketQuote + akshare 均失败），返回空列表",
        symbol,
        days,
    )
    return []


def fetch_bars_250d(symbol: str) -> list[Bar]:
    """T0-8 · 近 250 日前复权 OHLCV（P1）。"""
    return fetch_bars(symbol, 250)
