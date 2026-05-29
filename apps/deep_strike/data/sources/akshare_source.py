"""akshare 数据源封装；支持 DEEP_STRIKE_MOCK=1 离线占位。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any


def _mock_enabled() -> bool:
    if os.environ.get("DEEP_STRIKE_MOCK", "").strip() != "1":
        return False
    from apps.common.no_mock_policy import reject_business_mock

    reject_business_mock("DEEP_STRIKE_MOCK", context="deep_strike data ingest")
    return True


def fetch_financial_report(symbol: str) -> list[dict[str, Any]]:
    if _mock_enabled():
        return [
            {
                "report_type": "income",
                "period": "2024Q3",
                "period_end": datetime(2024, 9, 30),
                "revenue": 1e9,
                "cost": 6e8,
                "gross_profit": 4e8,
                "operating_expense": 1e8,
                "net_profit": 2e8,
                "raw": {"mock": True},
            }
        ]
    import akshare as ak  # noqa: PLC0415

    rows: list[dict[str, Any]] = []
    try:
        df = ak.stock_financial_report_sina(stock=symbol, symbol="资产负债表")
        for _, row in df.head(8).iterrows():
            rows.append(
                {
                    "report_type": "balance",
                    "period": str(row.get("报告期", "2024Q3")),
                    "period_end": datetime(2024, 9, 30),
                    "revenue": None,
                    "cost": None,
                    "gross_profit": None,
                    "operating_expense": None,
                    "net_profit": None,
                    "raw": row.to_dict(),
                }
            )
    except Exception:
        rows.append(
            {
                "report_type": "income",
                "period": "2024Q3",
                "period_end": datetime(2024, 9, 30),
                "revenue": None,
                "cost": None,
                "gross_profit": None,
                "operating_expense": None,
                "net_profit": None,
                "raw": {"error": "akshare_financial_report"},
            }
        )
    return rows


def fetch_financial_indicator(symbol: str) -> list[dict[str, Any]]:
    if _mock_enabled():
        from datetime import timedelta

        rows: list[dict[str, Any]] = []
        base = datetime(2022, 12, 31)
        for i in range(8):
            period_end = base + timedelta(days=91 * (i + 1))
            qn = (i % 4) + 1
            year = 2023 + (i // 4)
            gm = 0.20 + i * 0.01
            rec_t = 3.5 + i * 0.15
            # 最新一期 (i=7) 指标对齐利润截留 5 信号全命中（step_04 扫描读最新行）
            if i == 7:
                rows.append(
                    {
                        "period": f"{year}Q{qn}",
                        "period_end": period_end,
                        "gross_margin": 0.27,
                        "gross_margin_qoq": 0.025,
                        "gross_margin_yoy": 0.02,
                        "revenue_growth_yoy": 0.15,
                        "cost_growth_yoy": 0.05,
                        "net_profit_growth_yoy": 0.26,
                        "receivable_turnover": rec_t,
                        "receivable_turnover_qoq": 0.1,
                        "inventory_turnover": 3.0,
                        "inventory_turnover_qoq": 0.1,
                        "pe": 15.0,
                        "pb": 2.0,
                        "raw": {"mock": True, "quarter_index": i, "profit_capture_tail": True},
                    }
                )
            else:
                rows.append(
                    {
                        "period": f"{year}Q{qn}",
                        "period_end": period_end,
                        "gross_margin": gm,
                        "gross_margin_qoq": 0.025 if i else None,
                        "gross_margin_yoy": 0.02,
                        "revenue_growth_yoy": 0.10 + i * 0.002,
                        "cost_growth_yoy": 0.08 + i * 0.001,
                        "net_profit_growth_yoy": 0.12 + i * 0.005,
                        "receivable_turnover": rec_t,
                        "receivable_turnover_qoq": None,
                        "inventory_turnover": 3.0,
                        "inventory_turnover_qoq": None,
                        "pe": 15.0,
                        "pb": 2.0,
                        "raw": {"mock": True, "quarter_index": i},
                    }
                )
        return rows
    import akshare as ak  # noqa: PLC0415

    try:
        df = ak.stock_financial_analysis_indicator(symbol=symbol)
        out = []
        for _, row in df.head(8).iterrows():
            out.append(
                {
                    "period": str(row.get("日期", "2024Q3")),
                    "period_end": datetime(2024, 9, 30),
                    "gross_margin": float(row["销售毛利率"]) if "销售毛利率" in row and row["销售毛利率"] else None,
                    "gross_margin_qoq": None,
                    "gross_margin_yoy": None,
                    "revenue_growth_yoy": None,
                    "cost_growth_yoy": None,
                    "net_profit_growth_yoy": None,
                    "receivable_turnover": None,
                    "receivable_turnover_qoq": None,
                    "inventory_turnover": None,
                    "inventory_turnover_qoq": None,
                    "pe": None,
                    "pb": None,
                    "raw": row.to_dict(),
                }
            )
        return out
    except Exception:
        return [
            {
                "period": "2024Q3",
                "period_end": datetime(2024, 9, 30),
                "gross_margin": None,
                "gross_margin_qoq": None,
                "gross_margin_yoy": None,
                "revenue_growth_yoy": None,
                "cost_growth_yoy": None,
                "net_profit_growth_yoy": None,
                "receivable_turnover": None,
                "receivable_turnover_qoq": None,
                "inventory_turnover": None,
                "inventory_turnover_qoq": None,
                "pe": None,
                "pb": None,
                "raw": {"error": "akshare_indicator"},
            }
        ]


def fetch_announcements(symbol: str, days: int = 30) -> list[dict[str, Any]]:
    if _mock_enabled():
        return [
            {
                "announcement_id": f"mock-{symbol}-1",
                "title": f"{symbol}  Quarterly report summary",
                "published_at": datetime(2024, 5, 1),
                "url": "https://example.com/a1",
                "summary": "主营收入增长符合预期",
                "full_text": None,
                "source": "mock",
                "raw": {},
            },
            {
                "announcement_id": f"mock-{symbol}-2",
                "title": f"{symbol}  production capacity note",
                "published_at": datetime(2024, 4, 15),
                "url": "https://example.com/a2",
                "summary": "产能利用率回升",
                "full_text": None,
                "source": "mock",
                "raw": {},
            },
        ]
    import akshare as ak  # noqa: PLC0415

    try:
        df = ak.stock_notice_report(symbol=symbol)
        rows = []
        for _, row in df.head(20).iterrows():
            rows.append(
                {
                    "announcement_id": str(row.get("公告编号", row.get("标题", "na"))),
                    "title": str(row.get("标题", ""))[:500],
                    "published_at": datetime(2024, 5, 1),
                    "url": row.get("公告链接"),
                    "summary": None,
                    "full_text": None,
                    "source": "akshare",
                    "raw": row.to_dict(),
                }
            )
        return rows
    except Exception:
        return []


def fetch_industry_peers(symbol: str) -> list[dict[str, Any]]:
    if _mock_enabled():
        return [
            {
                "industry_code": "BK0428",
                "industry_name": "白色家电",
                "peer_symbol": "000333",
                "peer_name": "美的集团",
                "peer_metric_snapshot": {"gross_margin": 0.24},
            },
            {
                "industry_code": "BK0428",
                "industry_name": "白色家电",
                "peer_symbol": "000651",
                "peer_name": "格力电器",
                "peer_metric_snapshot": {"gross_margin": 0.26},
            },
            {
                "industry_code": "BK0428",
                "industry_name": "白色家电",
                "peer_symbol": "000100",
                "peer_name": "TCL科技",
                "peer_metric_snapshot": {"gross_margin": 0.18},
            },
        ]
    return []


def fetch_realtime_quote(symbol: str) -> dict[str, Any]:
    if _mock_enabled():
        return {"symbol": symbol, "price": 10.0, "raw": {"mock": True}}
    import akshare as ak  # noqa: PLC0415

    try:
        df = ak.stock_bid_ask_em(symbol=symbol)
        return {"symbol": symbol, "price": float(df.iloc[0]["最新"]) if len(df) else 0.0, "raw": df.head(1).to_dict()}
    except Exception:
        return {"symbol": symbol, "price": 0.0, "raw": {}}
