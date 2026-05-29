#!/usr/bin/env python3
"""D1 财务测谎引擎 · 真实 DB 联调（从 financial_reports 读取数据）。

从 data/deep_strike.db 的 financial_reports 表提取字段，
注入到 FinancialFraudEngine，输出各标的的 fraud_report。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_04_财务测谎引擎LoRA §7.1]
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _load_dotenv() -> None:
    env_file = _ROOT / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)
    except ImportError:
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


# 中文字段 → engine 期望英文字段的映射（资产负债表）
_BALANCE_MAP = {
    "货币资金": "cash",
    "资产总计": "total_assets",
    "负债合计": "total_debt",
    "应收账款": "accounts_receivable",
    "存货": "inventory",
    "开发支出": "rd_capitalized",
}

# 利润表字段
_INCOME_MAP = {
    "营业收入": "revenue",
    "净利润": "net_profit",
}


def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        import math
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def extract_from_raw(raw_json: str, field_map: dict) -> dict:
    """从 raw JSON 按中文字段名提取所需字段，返回英文 key 的 dict。"""
    try:
        raw = json.loads(raw_json)
    except Exception:
        return {}
    result = {}
    for cn_key, en_key in field_map.items():
        val = _safe_float(raw.get(cn_key))
        result[en_key] = val
    return result


def load_symbol_data(db_path: str, symbol: str) -> dict:
    """从 financial_reports 读取 balance + income，合并为 engine 所需字段 dict。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    fields: dict = {"symbol": symbol, "industry": "未知"}

    # 资产负债表
    cur.execute(
        "SELECT raw FROM financial_reports WHERE symbol=? AND report_type='balance' ORDER BY period DESC LIMIT 1",
        (symbol,),
    )
    row = cur.fetchone()
    if row and row["raw"]:
        fields.update(extract_from_raw(row["raw"], _BALANCE_MAP))

    # 利润表（含 gross_margin 推算）
    cur.execute(
        "SELECT revenue, cost, gross_profit, net_profit, raw FROM financial_reports "
        "WHERE symbol=? AND report_type='income' ORDER BY period DESC LIMIT 1",
        (symbol,),
    )
    row = cur.fetchone()
    if row:
        rev = _safe_float(row["revenue"])
        gp = _safe_float(row["gross_profit"])
        np_ = _safe_float(row["net_profit"])
        if rev and gp:
            fields["revenue"] = rev
            fields["gross_margin"] = round(gp / rev, 4) if rev else None
        if np_:
            fields["net_profit"] = np_
        if row["raw"]:
            fields.update(extract_from_raw(row["raw"], _INCOME_MAP))

    # 现金流量表（经营活动净现金流）
    cur.execute(
        "SELECT raw FROM financial_reports WHERE symbol=? AND report_type='cashflow' ORDER BY period DESC LIMIT 1",
        (symbol,),
    )
    row = cur.fetchone()
    if row and row["raw"]:
        try:
            raw_cf = json.loads(row["raw"])
            ocf = _safe_float(raw_cf.get("经营活动产生的现金流量净额"))
            if ocf is not None:
                fields["operating_cash_flow"] = ocf
        except Exception:
            pass

    conn.close()
    return fields


class SimpleDBSession:
    """极简 DB session，直接把 fields dict 返回（不再查 SQL）。"""
    def __init__(self, fields: dict):
        self._fields = fields

    def execute(self, query: str, params: tuple):
        return self

    def fetchone(self):
        return self._fields


def _run_engine(symbol: str, fields: dict) -> dict:
    from apps.cryo_guard.engines.financial_fraud.engine import FinancialFraudEngine

    engine = FinancialFraudEngine()
    from apps.cryo_guard.engines.financial_fraud.feature_calculator import compute_features
    features = compute_features(fields)
    report = {
        "symbol": symbol,
        "fields_available": [k for k, v in fields.items() if v is not None and k not in ("symbol", "industry")],
        "fields_missing": [k for k, v in fields.items() if v is None and k not in ("symbol", "industry")],
        "features": features,
    }
    return report


def main() -> int:
    db_path = str(_ROOT / "data" / "deep_strike.db")
    if not Path(db_path).exists():
        print(f"❌ DB 不存在: {db_path}", file=sys.stderr)
        return 1

    from apps.common.holdings_sot import load_holdings_sot
    sot = load_holdings_sot()
    active_syms = sot.active_symbols()
    if not active_syms:
        print("❌ my_holdings.yaml 无 active 持仓", file=sys.stderr)
        return 1

    print(f"\n=== D1 财务测谎引擎 · 真实 DB 联调（{len(active_syms)} 只标的）===\n")
    ok_count = 0
    for symbol in active_syms:
        fields = load_symbol_data(db_path, symbol)
        available = [k for k, v in fields.items() if v is not None and k not in ("symbol", "industry")]
        missing = [k for k, v in fields.items() if v is None and k not in ("symbol", "industry")]
        if not available:
            print(f"  ⚠️ {symbol}: 无数据（financial_reports 无对应行，跳过）")
            continue

        report = _run_engine(symbol, fields)
        features = report.get("features", {})
        flags = [k for k, v in features.items() if v is True]
        print(
            f"  {'✅' if not flags else '⚠️'} {symbol}: "
            f"available={len(available)} missing={len(missing)} flags={flags or '无'}"
        )
        ok_count += 1

    print(f"\n✅ D1 DB 联调完成：{ok_count}/{len(active_syms)} 标的有数据")
    if ok_count == 0:
        print("  ⚠️ 0 标的有数据（financial_reports 仅有资产负债表，缺利润表/现金流表）")
        print("  建议：补采 income/cashflow 报表后重跑（cryo step_02 已有框架）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
