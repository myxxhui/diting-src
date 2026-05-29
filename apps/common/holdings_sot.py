"""持仓 SoT（Single source of truth）加载器。

启动期所有维度的数据采集 / 推断 / 持仓体检都从本 SoT 拉取标的清单：
- D1 财报与公告采集（cryo_guard）
- D2 thesis 候选池（deep_strike，启动期叠加候选池前的最小集）
- D3 持仓监控状态机（holding_watch）
- D4 卖出协议持仓行情（exit_engine）
- D0 副驾驶持仓 CRUD（co_pilot）

SoT 文件位置由环境变量 `MY_HOLDINGS_YAML` 决定，默认
``data/config/my_holdings.yaml``。模板见
``data/config/my_holdings.example.yaml``。

[Ref: 03_/_共享规约/14_六维度启动期统一节奏表.md · 持仓 SoT]
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, List, Optional

import yaml


DEFAULT_HOLDINGS_PATH = "data/config/my_holdings.yaml"
EXAMPLE_HOLDINGS_PATH = "data/config/my_holdings.example.yaml"


@dataclass(frozen=True)
class HoldingEntry:
    """SoT 中的一只标的。

    ``role``：
    - ``portfolio`` — 真实持仓（D4 卖出 / 盈亏同步）
    - ``watchlist`` — 关注标的（D1 采集 / D3 探针，不同步 D4）
    """

    symbol: str
    name: str
    active: bool = True
    role: str = "watchlist"
    quantity: float = 0.0
    cost_price: float = 0.0
    opened_at: Optional[date] = None
    segment: Optional[str] = None
    notes: Optional[str] = None


@dataclass(frozen=True)
class HoldingsSot:
    holdings: List[HoldingEntry]
    crawl_years: List[int]
    throttle_sec: float
    source_path: Path

    def active_symbols(self) -> List[str]:
        """全部 ``active=true`` 标的（真实持仓 + 关注）。"""
        return [h.symbol for h in self.holdings if h.active]

    def portfolio_symbols(self) -> List[str]:
        """真实持仓：``role=portfolio`` 且 active。"""
        return [h.symbol for h in self.holdings if h.active and h.role == "portfolio"]

    def watchlist_symbols(self) -> List[str]:
        """关注标的：``role=watchlist`` 且 active。"""
        return [h.symbol for h in self.holdings if h.active and h.role == "watchlist"]

    def by_symbol(self, symbol: str) -> Optional[HoldingEntry]:
        for h in self.holdings:
            if h.symbol == symbol:
                return h
        return None


def _coerce_date(value: object) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _coerce_str(value: object) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _resolve_role(item: dict, quantity: float, cost_price: float) -> str:
    """解析 role；未写时 qty+cost 均 >0 视为 portfolio，否则 watchlist。"""
    explicit = _coerce_str(item.get("role"))
    if explicit:
        role = explicit.lower()
        if role in ("portfolio", "watchlist"):
            return role
    if quantity > 0 and cost_price > 0:
        return "portfolio"
    return "watchlist"


def load_holdings_sot(path: Optional[str | os.PathLike[str]] = None) -> HoldingsSot:
    """从 yaml 加载持仓 SoT；找不到主文件时自动回退到 example。

    返回的 ``HoldingsSot`` 始终至少含一条 entry（example 模板中预置）。
    """

    candidates: list[Path] = []
    explicit = path or os.environ.get("MY_HOLDINGS_YAML")
    if explicit:
        candidates.append(Path(explicit))
    candidates.extend(
        [Path(DEFAULT_HOLDINGS_PATH), Path(EXAMPLE_HOLDINGS_PATH)]
    )

    resolved: Optional[Path] = None
    for c in candidates:
        if c.exists():
            resolved = c
            break
    if resolved is None:
        raise FileNotFoundError(
            "持仓 SoT 未找到；请按 data/config/my_holdings.example.yaml 复制为 "
            "data/config/my_holdings.yaml，或显式设置 MY_HOLDINGS_YAML"
        )

    with resolved.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    items_raw: Iterable[dict] = raw.get("holdings") or []
    holdings: list[HoldingEntry] = []
    for item in items_raw:
        if not item or not item.get("symbol"):
            continue
        qty = float(item.get("quantity") or 0.0)
        cost = float(item.get("cost_price") or 0.0)
        holdings.append(
            HoldingEntry(
                symbol=str(item.get("symbol")).strip(),
                name=str(item.get("name", "")).strip(),
                active=bool(item.get("active", True)),
                role=_resolve_role(item, qty, cost),
                quantity=qty,
                cost_price=cost,
                opened_at=_coerce_date(item.get("opened_at")),
                segment=_coerce_str(item.get("segment")),
                notes=_coerce_str(item.get("notes")),
            )
        )

    defaults = raw.get("defaults") or {}
    years_raw = defaults.get("crawl_years") or []
    crawl_years = [int(y) for y in years_raw if str(y).isdigit()]
    throttle_sec = float(defaults.get("throttle_sec") or 0.6)

    return HoldingsSot(
        holdings=holdings,
        crawl_years=crawl_years,
        throttle_sec=throttle_sec,
        source_path=resolved,
    )


def active_symbols(path: Optional[str | os.PathLike[str]] = None) -> List[str]:
    """便捷函数：返回当前 SoT 中所有 ``active=true`` 标的 6 位代码。"""

    return load_holdings_sot(path).active_symbols()
