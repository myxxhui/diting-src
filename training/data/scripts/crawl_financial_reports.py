"""全 A 股近 5 年财务报表采集（akshare）。

**配置写在哪**：优先在仓库根 ``diting-src/.env`` 里写 ``CRYO_*``（脚本启动时会
``load_dotenv``，**不**覆盖你在 shell 里已 export 的变量）；或使用 YAML：
复制 ``training/data/config/crawl_financial.example.yaml`` → 自定路径，并设置
``CRYO_CRAWL_CONFIG=相对或绝对路径``（仍可在 .env 里写该项）。

环境变量：
  CRYO_MOCK=1 — **已禁用**（no-mock-policy；仅 tests/ 内 pytest 可临时使用）
  CRYO_MAX_SYMBOLS=N — 在最终标的列表上仅保留前 N 只（可与清单联用）
  CRYO_SYMBOL_LIST — 标的清单文件路径（每行：代码 + 制表符 / 英文逗号 / **空白** + 简称）；设置后 **不** 拉全 A；**代码须为 6 位，脚本会转为东财 sh/sz 前缀再请求 akshare**
  CRYO_YEARS — 逗号分隔报告年度，如 2022,2023,2024（优先于 YEAR_START/END）
  CRYO_YEAR_START / CRYO_YEAR_END — 含端点区间，如 2022 与 2024 → 2022..2024
  CRYO_REPORT_TYPES — 逗号分隔：annual,semi,q1,q3（默认 annual）
  CRYO_THROTTLE_SEC — 每次 ak 请求后睡眠秒数（默认 0.6）
  CRYO_CRAWL_CONFIG — 可选，指向 YAML（见 training/data/config/crawl_financial.example.yaml）

``env_crawl_interval_dates()`` 将上述年度解析为 ``[Y_min-01-01, Y_max-12-31]``，供 ``crawl_announcements`` 等同源时间窗复用。

[Ref: 03_/01_维度一_极寒防御/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from apps.cryo_guard.crawl_env_bootstrap import bootstrap_crawl_env

bootstrap_crawl_env(_REPO_ROOT)

import logging
import os
import time
from datetime import date
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session
from tqdm import tqdm

from apps.cryo_guard.db.models import FinancialReport
from apps.cryo_guard.db.sync_session import session_scope

logger = logging.getLogger(__name__)

REPORT_TYPES = {"annual": "12-31", "semi": "06-30", "q1": "03-31", "q3": "09-30"}


def parse_symbol_list_file(path: Path) -> list[tuple[str, str]]:
    """解析标的清单：每行 code +（制表符 | 英文逗号 | 空白）+ name；# 开头为注释；仅代码时 name=code。"""
    out: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            code, _, rest = line.partition("\t")
            code = code.strip()
            name = (rest.strip() or code)
        elif "," in line:
            parts = [p.strip() for p in line.split(",", 1)]
            code = parts[0]
            name = parts[1] if len(parts) > 1 and parts[1] else code
        else:
            parts = line.split(None, 1)
            code = parts[0].strip()
            name = parts[1].strip() if len(parts) > 1 else code
        if code:
            out.append((code, name))
    return out


def env_crawl_years() -> list[int]:
    raw = os.environ.get("CRYO_YEARS", "").strip()
    if raw:
        ys: list[int] = []
        for part in raw.split(","):
            part = part.strip()
            if part:
                ys.append(int(part))
        return sorted(set(ys))
    start_e = os.environ.get("CRYO_YEAR_START", "").strip()
    end_e = os.environ.get("CRYO_YEAR_END", "").strip()
    if start_e and end_e:
        a, b = int(start_e), int(end_e)
        if a > b:
            a, b = b, a
        return list(range(a, b + 1))
    if start_e or end_e:
        raise ValueError("CRYO_YEAR_START 与 CRYO_YEAR_END 需同时设置，或改用 CRYO_YEARS")
    return list(range(2020, 2025))


def env_crawl_interval_dates() -> tuple[date, date]:
    """与 ``env_crawl_years()`` 对应的自然日闭区间，供同源时间窗复用（如公告采集）。

    返回 ``(min_year-01-01, max_year-12-31)``，解析规则与 ``CRYO_YEARS`` /
    ``CRYO_YEAR_START`` / ``CRYO_YEAR_END`` 完全一致。
    """
    years = env_crawl_years()
    y0, y1 = min(years), max(years)
    return date(y0, 1, 1), date(y1, 12, 31)


def env_report_types() -> tuple[str, ...]:
    raw = os.environ.get("CRYO_REPORT_TYPES", "").strip()
    if not raw:
        return ("annual",)
    types: list[str] = []
    for part in raw.split(","):
        part = part.strip().lower()
        if not part:
            continue
        if part not in REPORT_TYPES:
            raise ValueError(
                f"CRYO_REPORT_TYPES 含未知类型 {part!r}，可选: {sorted(REPORT_TYPES)}"
            )
        types.append(part)
    return tuple(types) if types else ("annual",)


def env_throttle_sec() -> float:
    raw = os.environ.get("CRYO_THROTTLE_SEC", "").strip()
    if not raw:
        return 0.6
    return max(0.0, float(raw))


def _safe_float(v):  # noqa: ANN001
    if v is None or v == "" or v == "-" or v == "--":
        return None
    try:
        x = float(str(v).replace(",", ""))
        if x != x:  # NaN
            return None
        return x
    except (ValueError, TypeError):
        return None


def _row_float(row: dict, *keys: str) -> float | None:
    """同一指标优先中文列名（部分 ak 接口），否则东财 EM 英文列名。"""
    for k in keys:
        if not k:
            continue
        v = _safe_float(row.get(k))
        if v is not None:
            return v
    return None


def _eastmoney_symbol(symbol: str) -> str:
    """东财 ``*_by_report_em`` 接口要求：``sh600519`` / ``sz000001``（纯 6 位会触发内部 None 错误）。"""
    s = symbol.strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    if not s.isdigit():
        return symbol.strip()
    s = s.zfill(6)[-6:]
    # 北交所 8/4 开头可按需扩展 bj；常见沪深：6/9→沪，其余→深
    if s.startswith(("5", "6", "9")):
        return f"sh{s}"
    return f"sz{s}"


def get_all_a_stock_symbols() -> list[tuple[str, str]]:
    if os.environ.get("CRYO_MOCK", "").strip() == "1":
        return [("600519", "贵州茅台"), ("000001", "平安银行")]
    list_path = os.environ.get("CRYO_SYMBOL_LIST", "").strip()
    if list_path:
        p = Path(list_path).expanduser()
        if not p.is_file():
            raise FileNotFoundError(
                f"CRYO_SYMBOL_LIST={list_path!r} 不是可读文件；请创建清单或取消该变量以拉全 A"
            )
        syms = parse_symbol_list_file(p)
        if not syms:
            raise ValueError(f"标的清单无有效行: {p}")
        logger.info("使用 CRYO_SYMBOL_LIST，共 %d 家 ← %s", len(syms), p.resolve())
        return syms
    import akshare as ak  # noqa: PLC0415

    df = ak.stock_info_a_code_name()
    return [(str(row["code"]), str(row["name"])) for _, row in df.iterrows()]


def _build_record(
    symbol: str,
    name: str,
    year: int,
    rep_type: str,
    bs_row: dict,
    is_row: dict,
    cf_row: dict,
) -> FinancialReport:
    rep_date = date.fromisoformat(f"{year}-{REPORT_TYPES[rep_type]}")
    revenue = _row_float(is_row, "营业总收入", "TOTAL_OPERATE_INCOME")
    cost = _row_float(
        is_row,
        "营业总成本",
        "TOTAL_OPERATE_COST",
        "营业成本",
        "OPERATE_COST",
    )
    net_profit = _row_float(is_row, "净利润", "NETPROFIT", "PARENT_NETPROFIT")
    total_assets = _row_float(bs_row, "资产总计", "总资产", "TOTAL_ASSETS")
    total_liabilities = _row_float(bs_row, "负债合计", "总负债", "TOTAL_LIABILITIES")
    equity = (
        (total_assets - total_liabilities)
        if total_assets is not None and total_liabilities is not None
        else None
    )
    roe = (net_profit / equity) if net_profit is not None and equity else None
    return FinancialReport(
        symbol=symbol,
        company_name=name,
        report_date=rep_date,
        report_type=rep_type,
        raw_balance_sheet=bs_row or {},
        raw_income_statement=is_row or {},
        raw_cash_flow=cf_row or {},
        cash_and_equivalents=_row_float(bs_row, "货币资金", "MONETARYFUNDS"),
        accounts_receivable=_row_float(bs_row, "应收账款", "ACCOUNTS_RECE", "NOTE_ACCOUNTS_RECE"),
        inventory=_row_float(bs_row, "存货", "INVENTORY"),
        total_assets=total_assets,
        short_term_debt=_row_float(bs_row, "短期借款", "SHORT_LOAN"),
        long_term_debt=_row_float(bs_row, "长期借款", "LONG_LOAN"),
        total_liabilities=total_liabilities,
        revenue=revenue,
        cost_of_revenue=cost,
        gross_profit=(revenue - cost) if revenue is not None and cost is not None else None,
        operating_profit=_row_float(is_row, "营业利润", "OPERATE_PROFIT"),
        net_profit=net_profit,
        rd_expense=_row_float(is_row, "研发费用", "RESEARCH_EXPENSE", "RD_EXPENSE"),
        rd_capitalized=_row_float(
            is_row,
            "研发支出资本化",
            "开发支出",
            "RD_EXPENDITURE_CAPITALIZED",
        ),
        operating_cash_flow=_row_float(
            cf_row,
            "经营活动产生的现金流量净额",
            "NETCASH_OPERATE",
            "NETCASH_OPERATENOTE",
        ),
        investing_cash_flow=_row_float(cf_row, "投资活动产生的现金流量净额", "NETCASH_INVEST"),
        financing_cash_flow=_row_float(cf_row, "筹资活动产生的现金流量净额", "NETCASH_FINANCE"),
        gross_margin=(1 - cost / revenue) if revenue and cost else None,
        net_margin=(net_profit / revenue) if revenue and net_profit is not None else None,
        roe=roe,
        source="akshare",
    )


def _build_mock_record(symbol: str, name: str, year: int, rep_type: str) -> FinancialReport:
    rep_date = date.fromisoformat(f"{year}-{REPORT_TYPES[rep_type]}")
    return FinancialReport(
        symbol=symbol,
        company_name=name,
        report_date=rep_date,
        report_type=rep_type,
        raw_balance_sheet={"mock": True},
        raw_income_statement={"mock": True},
        raw_cash_flow={"mock": True},
        revenue=1e9,
        net_profit=1e8,
        source="mock",
    )


def crawl_one(symbol: str, name: str, year: int, rep_type: str, session: Session) -> bool:
    rep_d = date.fromisoformat(f"{year}-{REPORT_TYPES[rep_type]}")
    exists = session.scalar(
        select(FinancialReport.id).where(
            FinancialReport.symbol == symbol,
            FinancialReport.report_date == rep_d,
            FinancialReport.report_type == rep_type,
        )
    )
    if exists:
        return False
    if os.environ.get("CRYO_MOCK", "").strip() == "1":
        session.add(_build_mock_record(symbol, name, year, rep_type))
        session.commit()
        return True
    import akshare as ak  # noqa: PLC0415

    em = _eastmoney_symbol(symbol)
    try:
        bs = ak.stock_balance_sheet_by_report_em(symbol=em)
        is_ = ak.stock_profit_sheet_by_report_em(symbol=em)
        cf = ak.stock_cash_flow_sheet_by_report_em(symbol=em)
    except Exception as exc:
        logger.warning("akshare 拉取失败 %s (%s) %s: %s", symbol, em, year, exc)
        return False
    bs_row = next((r for r in bs.to_dict("records") if str(year) in str(r.get("REPORT_DATE", ""))), {})
    is_row = next((r for r in is_.to_dict("records") if str(year) in str(r.get("REPORT_DATE", ""))), {})
    cf_row = next((r for r in cf.to_dict("records") if str(year) in str(r.get("REPORT_DATE", ""))), {})
    if not bs_row:
        return False
    session.add(_build_record(symbol, name, year, rep_type, bs_row, is_row, cf_row))
    session.commit()
    return True


def main(
    years: Iterable[int] | None = None,
    report_types: Iterable[str] | None = None,
    throttle_sec: float | None = None,
) -> None:
    from apps.common.no_mock_policy import reject_business_mock

    reject_business_mock("CRYO_MOCK", context="crawl_financial_reports")
    if years is None:
        years = env_crawl_years()
    if report_types is None:
        report_types = env_report_types()
    if throttle_sec is None:
        throttle_sec = env_throttle_sec()
    years = list(years)
    report_types = list(report_types)
    syms = get_all_a_stock_symbols()
    max_n = os.environ.get("CRYO_MAX_SYMBOLS")
    if max_n and max_n.isdigit():
        syms = syms[: int(max_n)]
    logger.info("共 %d 家，将采集 %s 年 %s 报表", len(syms), years, report_types)
    with session_scope() as session:
        for symbol, name in tqdm(syms, desc="采集财报"):
            for year in years:
                for rep_type in report_types:
                    if crawl_one(symbol, name, year, rep_type, session):
                        pass
                    time.sleep(throttle_sec)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    main()
