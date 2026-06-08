"""#16 volume_price_div · 15 分钟 K 线 T0（东财 push2his · 腾讯 mkline 回退 · Redis）。

香港 Pod 实测：push2his 不可达、push2delay 15m 空集；腾讯 mkline m15 稳定可用（[Ref: 21_ §四]）。

[Ref: 28_ §2.2 · §4.4 · 21_]
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from apps.common.market_quote.exchange import tencent_code
from apps.copilot.db.datetime_util import shanghai_now_iso
from apps.copilot.modules.radar.t0.collectors._em_fetch import _PUSH2, em_get_json

logger = logging.getLogger(__name__)

BARS_15M_KEY = "executing:bars_15m:{symbol}"
BARS_15M_TTL_SEC = 36000
LOOKBACK_BARS = 200
MIN_BARS_ACCEPT = 160
SOURCE_EM_15M = "eastmoney_push2his_15m_qfq"
SOURCE_TENCENT_15M = "tencent_mkline_m15_qfq"
PERIOD = "15m"
_TENCENT_MKLINE_URL = "https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={param}"
_TENCENT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; diting-executing/1.0)",
    "Referer": "https://gu.qq.com/",
}


@dataclass(frozen=True)
class Bar15m:
    datetime: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def _sym(symbol: str) -> str:
    return symbol.zfill(6)[-6:]


def _secid(sym: str) -> str:
    market = "1" if sym.startswith("6") else "0"
    return f"{market}.{sym}"


def _format_tencent_dt(raw: str) -> str:
    s = str(raw).strip()
    if len(s) == 12 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}"
    return s


def _parse_em_klines(klines: list[Any]) -> list[Bar15m]:
    bars: list[Bar15m] = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        try:
            bars.append(
                Bar15m(
                    datetime=str(parts[0]),
                    open=float(parts[1]),
                    close=float(parts[2]),
                    high=float(parts[3]),
                    low=float(parts[4]),
                    volume=float(parts[5]),
                )
            )
        except (TypeError, ValueError):
            continue
    return bars


def _fetch_em_15m(sym: str) -> list[Bar15m]:
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": "15",
        "fqt": "1",
        "secid": _secid(sym),
        "beg": "0",
        "end": "20500000",
        "lmt": str(LOOKBACK_BARS + 40),
        "_": int(time.time() * 1000),
    }
    bases = (
        _PUSH2,
        "https://push2his.eastmoney.com",
        "https://33.push2his.eastmoney.com",
        "https://7.push2his.eastmoney.com",
        "https://push2.eastmoney.com",
    )
    for base in bases:
        payload = em_get_json(
            f"{base.rstrip('/')}/api/qt/stock/kline/get",
            params={**params, "_": int(time.time() * 1000)},
            referer=f"https://quote.eastmoney.com/concept/sh{sym}.html",
            retries=3,
        )
        klines = (payload.get("data") or {}).get("klines") if payload else None
        if klines:
            return _parse_em_klines(klines)
    return []


def _fetch_tencent_15m(sym: str, *, lookback: int) -> list[Bar15m]:
    """腾讯 mkline m15 · 香港 Pod 主可用源（push2his 阻断时）。"""
    code = tencent_code(sym)
    count = min(max(lookback + 20, MIN_BARS_ACCEPT + 20), 320)
    param = f"{code},m15,,,{count},qfq"
    try:
        resp = httpx.get(
            _TENCENT_MKLINE_URL.format(param=param),
            headers=_TENCENT_HEADERS,
            timeout=15.0,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("腾讯 mkline m15 失败 symbol=%s: %s", sym, exc)
        return []
    rows = ((payload.get("data") or {}).get(code) or {}).get("m15") or []
    bars: list[Bar15m] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            bars.append(
                Bar15m(
                    datetime=_format_tencent_dt(row[0]),
                    open=float(row[1]),
                    close=float(row[2]),
                    high=float(row[3]),
                    low=float(row[4]),
                    volume=float(row[5]),
                )
            )
        except (TypeError, ValueError):
            continue
    if len(bars) > lookback:
        bars = bars[-lookback:]
    return bars


def _fetch_akshare_fallback(symbol: str, *, lookback: int) -> list[Bar15m]:
    """末级回退（香港 Pod 通常仍走 push2his · 易失败）。"""
    try:
        import akshare as ak  # type: ignore

        from apps.copilot.modules.executing.t0_collectors import _ak_call

        df = _ak_call(ak.stock_zh_a_hist_min_em, symbol=symbol, period="15", adjust="qfq")
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare 15m 回退失败 symbol=%s: %s", symbol, exc)
        return []
    if df is None or df.empty:
        return []
    bars: list[Bar15m] = []
    for _, row in df.iterrows():
        try:
            bars.append(
                Bar15m(
                    datetime=str(row["时间"]),
                    open=float(row["开盘"]),
                    close=float(row["收盘"]),
                    high=float(row["最高"]),
                    low=float(row["最低"]),
                    volume=float(row["成交量"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    if len(bars) > lookback:
        bars = bars[-lookback:]
    return bars


def fetch_bars_15m_em(
    symbol: str,
    *,
    lookback: int = LOOKBACK_BARS,
    min_bars: int = MIN_BARS_ACCEPT,
) -> tuple[list[Bar15m], str]:
    """15min 前复权 K 线 · 东财优先 → 腾讯 mkline → akshare。"""
    sym = _sym(symbol)

    bars = _fetch_em_15m(sym)
    if len(bars) >= min_bars:
        if len(bars) > lookback:
            bars = bars[-lookback:]
        return bars, SOURCE_EM_15M

    if bars:
        logger.info("15m 东财不足 symbol=%s got=%d · 尝试腾讯 mkline", sym, len(bars))
    else:
        logger.warning("15m 东财无数据 symbol=%s · 尝试腾讯 mkline", sym)

    bars = _fetch_tencent_15m(sym, lookback=lookback)
    if len(bars) >= min_bars:
        return bars, SOURCE_TENCENT_15M

    ak_bars = _fetch_akshare_fallback(sym, lookback=lookback)
    if len(ak_bars) >= min_bars:
        return ak_bars, "akshare_stock_zh_a_hist_min_em_15m_qfq"

    logger.warning(
        "15m K 线不足 symbol=%s got=%d need>=%d",
        sym,
        len(bars) or len(ak_bars),
        min_bars,
    )
    return [], SOURCE_EM_15M


def bars_to_payload(symbol: str, bars: list[Bar15m], *, source: str) -> dict[str, Any]:
    return {
        "symbol": _sym(symbol),
        "period": PERIOD,
        "source": source,
        "collected_at": shanghai_now_iso(),
        "bars_count": len(bars),
        "lookback_requested": LOOKBACK_BARS,
        "bars": [asdict(b) for b in bars],
    }


def save_bars_15m_redis(redis_client: Any, symbol: str, payload: dict[str, Any]) -> None:
    sym = _sym(symbol)
    redis_client.setex(
        BARS_15M_KEY.format(symbol=sym),
        BARS_15M_TTL_SEC,
        json.dumps(payload, ensure_ascii=False),
    )


def load_bars_15m_redis(redis_client: Any, symbol: str) -> dict[str, Any] | None:
    if redis_client is None:
        return None
    raw = redis_client.get(BARS_15M_KEY.format(symbol=_sym(symbol)))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
