"""Z0-M2 段 A 赛道发现 · 多源链 T1（Tushare > EM push2delay > akshare · no-mock）。

[Ref: 34_ §3.2 · 32_ §2.4.1]
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from apps.copilot.metrics.collectors.m2_policy_sectors import collect_policy_sector_direction
from apps.copilot.metrics.tushare_client import tushare_available, ts_call
from apps.copilot.modules.radar.t0.collectors._ak_util import ak_call
from apps.copilot.modules.radar.t0.collectors._em_fetch import (
    fetch_concept_boards,
    fetch_industry_boards,
    fetch_sector_fund_flow,
)

logger = logging.getLogger(__name__)


def _ok(data: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "metric_id": "M.sector.concept_heat",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "data": data,
        "source": source,
    }


def _err(detail: str) -> dict[str, Any]:
    return {"status": "error", "metric_id": "M.sector.concept_heat", "detail": detail}


def _rows_from_boards(boards: list[dict[str, Any]], *, name_key: str = "board_name") -> list[dict[str, Any]]:
    """v2.6：输出全维度数据（涨跌幅/换手率/PE/量比/总市值/涨跌家数/5日10日净流入/净占比）。"""
    rows: list[dict[str, Any]] = []
    for b in boards:
        sector = str(b.get(name_key) or b.get("board_name") or "").strip()
        if not sector:
            continue
        try:
            row = {"sector": sector, "change_pct": float(b.get("pct_chg") or 0)}
            if b.get("turnover_rate") is not None:
                row["turnover_rate"] = float(b["turnover_rate"])
            if b.get("pe_dynamic") is not None:
                row["pe_dynamic"] = float(b["pe_dynamic"])
            if b.get("volume_ratio") is not None:
                row["volume_ratio"] = float(b["volume_ratio"])
            if b.get("total_mv") is not None:
                row["total_mv"] = float(b["total_mv"])
            if b.get("up_count") is not None:
                row["up_count"] = int(b["up_count"])
            if b.get("down_count") is not None:
                row["down_count"] = int(b["down_count"])
            if b.get("net_inflow") is not None:
                row["net_inflow"] = float(b["net_inflow"])
            if b.get("net_inflow_5d") is not None:
                row["net_inflow_5d"] = float(b["net_inflow_5d"])
            if b.get("net_inflow_10d") is not None:
                row["net_inflow_10d"] = float(b["net_inflow_10d"])
            if b.get("net_inflow_ratio") is not None:
                row["net_inflow_ratio"] = float(b["net_inflow_ratio"])
        except (TypeError, ValueError):
            continue
        rows.append(row)
    return rows


def _rows_from_fund_flow(flows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for f in flows:
        sector = str(f.get("sector") or f.get("board_name") or "").strip()
        inflow = f.get("net_inflow") or f.get("main_net_inflow")
        if not sector:
            continue
        try:
            val = float(inflow)
        except (TypeError, ValueError):
            continue
        rows.append({"sector": sector, "change_pct": round(val / 1e8, 4)})
    rows.sort(key=lambda x: x["change_pct"], reverse=True)
    return rows


def _finalize(rows: list[dict[str, Any]], source: str, *, top_n: int) -> dict[str, Any]:
    if not rows:
        return _err(f"{source} 无有效行")
    rows.sort(key=lambda x: x["change_pct"], reverse=True)
    top = rows[:top_n]
    bottom = sorted(rows, key=lambda x: x["change_pct"])[:5]
    return _ok(
        {
            "top_sectors": top,
            "weak_sectors": bottom,
            "universe_size": len(rows),
            "all_rows": rows,  # v2.6：全量数据供 wind_scan 三维度评分
        },
        source,
    )


def _try_tushare_concept(*, top_n: int) -> dict[str, Any] | None:
    if not tushare_available():
        return None
    for api, label in (("ths_daily", "ths"), ("dc_daily", "dc")):
        try:
            ts_call(api, trade_date=datetime.now().strftime("%Y%m%d"))
            # 有权限时由后续 L4 扩展；当前 token 通常无权限
        except Exception:  # noqa: BLE001
            logger.debug("Tushare %s 无权限或不可用", api)
    return None


def collect_concept_sector_heat(*, top_n: int = 15) -> dict[str, Any]:
    """v2.6：全量采集概念板块（全部 ~200 个），top_n 仅控制 top_sectors 展示数量，全量数据通过 all_rows 返回。"""
    errors: list[str] = []

    _try_tushare_concept(top_n=top_n)

    try:
        boards = fetch_concept_boards(page_size=100, max_pages=4)  # 全量拉取 ~400 个概念板块
        rows = _rows_from_boards(boards)
        if rows:
            return _finalize(rows, "eastmoney:push2delay_concept", top_n=top_n)
        errors.append("em_concept:空列表")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"em_concept:{exc}")

    try:
        boards = fetch_industry_boards()
        rows = _rows_from_boards(boards)
        if rows:
            return _finalize(rows, "eastmoney:push2delay_industry_fallback", top_n=top_n)
        errors.append("em_industry:空列表")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"em_industry:{exc}")

    try:
        flows = fetch_sector_fund_flow(indicator="今日")
        rows = _rows_from_fund_flow(flows)
        if rows:
            return _finalize(rows, "eastmoney:sector_fund_flow_fallback", top_n=top_n)
        errors.append("em_fund_flow:空")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"em_fund_flow:{exc}")

    try:
        import akshare as ak
    except ImportError:
        return _err(" · ".join(errors + ["akshare 不可用"]))

    spot = ak_call(ak.stock_board_concept_spot_em)
    if spot is None or spot.empty:
        names = ak_call(ak.stock_board_concept_name_em)
        if names is None or names.empty:
            return _err(" · ".join(errors + ["akshare 概念板块空/超时"]))
        spot = names

    name_col = "板块名称" if "板块名称" in spot.columns else spot.columns[0]
    chg_col = next((c for c in spot.columns if "涨跌幅" in str(c)), None)
    if chg_col is None:
        return _err(" · ".join(errors + ["akshare 缺涨跌幅列"]))

    rows_ak: list[dict[str, Any]] = []
    for _, r in spot.iterrows():
        sector = str(r.get(name_col, "")).strip()
        try:
            chg_f = float(r.get(chg_col))
        except (TypeError, ValueError):
            continue
        if sector:
            rows_ak.append({"sector": sector, "change_pct": chg_f})

    if not rows_ak:
        return _err(" · ".join(errors + ["akshare 无有效行"]))
    return _finalize(rows_ak, "akshare:stock_board_concept_spot_em", top_n=top_n)


def collect_m2_bundle(*, run_policy_ingest: bool = True) -> dict[str, Any]:
    ingest_part: dict[str, Any] | None = None
    if run_policy_ingest:
        from apps.copilot.services.deepsea.policy_ingest import ingest_policy_feeds
        from apps.copilot.services.deepsea.policy_t1_dispatcher import dispatch_policy_t1

        ingest_part = ingest_policy_feeds()
        t1_part = dispatch_policy_t1()
        ingest_part = {**ingest_part, "t1_dispatch": t1_part}
    heat = collect_concept_sector_heat()
    policy = collect_policy_sector_direction()
    parts: dict[str, Any] = {"concept_heat": heat, "policy_direction": policy}
    if ingest_part is not None:
        parts["policy_ingest"] = ingest_part
    ok_count = sum(1 for p in parts.values() if p.get("status") == "ok")
    status = "ok" if ok_count >= 1 else "error"
    detail = None
    if status != "ok":
        detail = " | ".join(
            f"{k}={p.get('detail', p.get('status'))}" for k, p in parts.items()
        )
    return {
        "status": status,
        "job_id": "z0-m2-sector-heat",
        "parts": parts,
        "ok_count": ok_count,
        "detail": detail,
    }
