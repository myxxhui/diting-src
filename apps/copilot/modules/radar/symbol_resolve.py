"""雷达扫描输入解析：6 位代码 / 简称 / 持仓 SoT / akshare 全市场 → (symbol, name)。

支持模糊简称匹配（difflib · 候选建议 API）。

[Ref: step_14 · 持仓 SoT]
"""
from __future__ import annotations

import difflib
import logging
import re
from functools import lru_cache
from typing import Any

from apps.common.holdings_sot import load_holdings_sot

logger = logging.getLogger(__name__)

# 自动解析最低置信（0~1）；低于此值须用户从建议列表点选
_FUZZY_AUTO_RESOLVE_MIN = 0.68
_SUGGEST_MIN_SCORE = 0.32


class RadarSymbolResolveError(ValueError):
    """无法将用户输入解析为 6 位 A 股代码。"""


def resolve_radar_query(query_text: str) -> tuple[str, str]:
    """解析模式 C 输入；优先数字代码，否则 SoT / 全市场精确，最后模糊匹配。"""
    raw = (query_text or "").strip()
    if not raw:
        raise RadarSymbolResolveError("请输入标的代码（6 位）或简称（如 英维克）")

    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 6:
        sym = digits[-6:]
        return sym, display_name_for_symbol(sym)
    if digits:
        sym = digits.zfill(6)[-6:]
        return sym, display_name_for_symbol(sym)

    from_sot = _resolve_from_sot(raw)
    if from_sot:
        sym, nm = from_sot
        return sym, display_name_for_symbol(sym, nm)

    from_market = _resolve_from_akshare_name(raw)
    if from_market:
        sym, nm = from_market
        return sym, display_name_for_symbol(sym, nm)

    fuzzy = suggest_radar_symbols(raw, limit=3)
    if fuzzy and fuzzy[0]["score"] >= _FUZZY_AUTO_RESOLVE_MIN:
        top = fuzzy[0]
        second = fuzzy[1]["score"] if len(fuzzy) > 1 else 0.0
        if top["score"] - second >= 0.08 or top["score"] >= 0.88:
            return top["symbol"], top["name"]

    hint = ""
    alts = suggest_radar_symbols(raw, limit=3)
    if alts:
        hint = "；您是否要找：" + "、".join(
            f"{a['name']}({a['symbol']})" for a in alts
        )
    raise RadarSymbolResolveError(
        f"未识别标的「{raw}」；请输入 6 位代码或 A 股简称{hint}"
    )


def _is_valid_chinese_name(name: str | None, sym: str) -> bool:
    nm = (name or "").strip()
    return bool(nm and nm != sym and not re.fullmatch(r"\d{1,6}", nm))


def _merge_sot_into_map(out: dict[str, str]) -> None:
    try:
        for h in load_holdings_sot().holdings:
            sym = h.symbol.zfill(6)[-6:]
            if len(sym) == 6 and _is_valid_chinese_name(h.name, sym):
                out[sym] = h.name.strip()
    except FileNotFoundError:
        pass


@lru_cache(maxsize=1)
def _code_name_map() -> dict[str, str]:
    """code→中文名（轻量 code_name 表优先 · 失败再试全市场 spot · 进程内缓存）。"""
    out: dict[str, str] = {}
    _merge_sot_into_map(out)

    try:
        import akshare as ak

        df = ak.stock_info_a_code_name()
        if df is not None and not df.empty:
            code_col = "code" if "code" in df.columns else "证券代码"
            name_col = "name" if "name" in df.columns else "证券简称"
            for _, row in df.iterrows():
                sym = re.sub(r"\D", "", str(row.get(code_col) or ""))[-6:]
                nm = str(row.get(name_col) or "").strip()
                if len(sym) == 6 and _is_valid_chinese_name(nm, sym):
                    out.setdefault(sym, nm)
    except Exception as exc:  # noqa: BLE001
        logger.warning("stock_info_a_code_name 索引失败: %s", exc)

    if len(out) < 1000:
        try:
            for nm, (s, name) in _a_share_name_index().items():
                if s not in out and _is_valid_chinese_name(name, s):
                    out[s] = name
        except Exception as exc:  # noqa: BLE001
            logger.warning("stock_zh_a_spot_em 索引失败: %s", exc)

    return out


def _resolve_name_single(sym: str) -> str:
    """单标的拉简称（profile 链 · 用于索引未命中时）。"""
    from apps.copilot.modules.radar.scanner import _collect_profile, _collect_profile_em

    try:
        em = _collect_profile_em(sym)
        if em.get("status") == "ok" and _is_valid_chinese_name(em.get("name"), sym):
            return str(em["name"]).strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve_name_single em %s: %s", sym, exc)
    try:
        out = _collect_profile(sym)
        if out.get("status") == "ok" and _is_valid_chinese_name(out.get("name"), sym):
            return str(out["name"]).strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve_name_single profile %s: %s", sym, exc)
    return sym


def display_name_for_symbol(
    symbol: str,
    name: str | None = None,
    *,
    allow_network: bool = True,
) -> str:
    """候选区主标题：库内名 → 内存 code 表 → 可选单标的补拉。"""
    sym = symbol.zfill(6)[-6:]
    if _is_valid_chinese_name(name, sym):
        return (name or "").strip()
    code_map = _code_name_map()
    if sym in code_map:
        return code_map[sym]
    if allow_network:
        resolved = _resolve_name_single(sym)
        if _is_valid_chinese_name(resolved, sym):
            return resolved
    return sym


def warm_market_name_index() -> int:
    """启动时后台预热 code→中文名表。"""
    try:
        return len(_code_name_map())
    except Exception as exc:  # noqa: BLE001
        logger.warning("预热 A 股简称索引失败: %s", exc)
        return 0


def suggest_radar_symbols(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """模糊搜索 A 股：代码前缀 / 简称包含 / 编辑距离。"""
    raw = (query or "").strip()
    if not raw:
        return []

    digits = re.sub(r"\D", "", raw)
    scored: dict[str, dict[str, Any]] = {}

    def _put(sym: str, name: str, score: float) -> None:
        sym = sym.zfill(6)[-6:]
        if len(sym) != 6 or score < _SUGGEST_MIN_SCORE:
            return
        prev = scored.get(sym)
        if prev is None or score > prev["score"]:
            scored[sym] = {"symbol": sym, "name": name, "score": round(score, 3)}

    if digits:
        for sym, (s, nm) in _iter_symbol_entries():
            if s.startswith(digits) or digits in s:
                _put(s, nm, 0.98 if s == digits.zfill(6)[-6:] else 0.88)

    for sym, (s, nm) in _iter_symbol_entries():
        if nm == raw:
            _put(s, nm, 1.0)
        elif nm.startswith(raw):
            _put(s, nm, 0.94)
        elif raw in nm or nm in raw:
            _put(s, nm, 0.86)
        else:
            ratio = difflib.SequenceMatcher(None, raw, nm).ratio()
            if ratio >= _SUGGEST_MIN_SCORE:
                _put(s, nm, ratio)

    out = sorted(scored.values(), key=lambda x: (-x["score"], x["symbol"]))
    return out[: max(1, limit)]


def _iter_symbol_entries() -> list[tuple[str, tuple[str, str]]]:
    """SoT + 内存 code 表（用于模糊建议，不强制拉 spot 全表）。"""
    entries: list[tuple[str, tuple[str, str]]] = []
    seen: set[str] = set()
    for sym, nm in _code_name_map().items():
        if sym not in seen:
            entries.append((sym, (sym, nm)))
            seen.add(sym)
    return entries


def _resolve_from_sot(raw: str) -> tuple[str, str] | None:
    try:
        sot = load_holdings_sot()
    except FileNotFoundError:
        return None
    for h in sot.holdings:
        if h.name == raw:
            sym = h.symbol.zfill(6)[-6:]
            return sym, h.name or sym
    for h in sot.holdings:
        if raw in (h.name or "") or (h.name or "") in raw:
            sym = h.symbol.zfill(6)[-6:]
            return sym, h.name or sym
    return None


@lru_cache(maxsize=1)
def _a_share_name_index() -> dict[str, tuple[str, str]]:
    """全 A 股 简称→(symbol,name)；进程内缓存。"""
    import akshare as ak

    df = ak.stock_zh_a_spot_em()
    if df is None or df.empty:
        return {}
    name_col = "名称" if "名称" in df.columns else ("name" if "name" in df.columns else None)
    code_col = "代码" if "代码" in df.columns else ("symbol" if "symbol" in df.columns else None)
    if not name_col or not code_col:
        return {}
    out: dict[str, tuple[str, str]] = {}
    for _, row in df.iterrows():
        nm = str(row.get(name_col) or "").strip()
        sym = re.sub(r"\D", "", str(row.get(code_col) or ""))[-6:]
        if nm and len(sym) == 6:
            out[nm] = (sym, nm)
    return out


def _resolve_from_akshare_name(raw: str) -> tuple[str, str] | None:
    try:
        idx = _a_share_name_index()
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare 简称索引失败: %s", exc)
        return None
    if raw in idx:
        return idx[raw]
    for nm, pair in idx.items():
        if raw in nm or nm in raw:
            return pair
    return None


def _resolve_name(symbol: str) -> str:
    return display_name_for_symbol(symbol, allow_network=True)
