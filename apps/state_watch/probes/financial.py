"""P1·财务探针(24h 调度).

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from apps.state_watch.probes.base_probe import BaseProbe, ProbeError, ProbeResult
from apps.state_watch.probes.datasource.akshare_adapter import fetch_financial_snapshot


class FinancialProbe(BaseProbe):
    probe_type = "financial"
    timeout_seconds = 30.0
    interval_hours = 24

    async def _fetch_impl(self, symbol: str) -> dict[str, Any]:
        snap = await asyncio.to_thread(fetch_financial_snapshot, symbol)
        if snap.report_date == "UNKNOWN":
            raise ProbeError(f"no financial data for {symbol}")

        return {
            "report_date": snap.report_date,
            "revenue": snap.revenue,
            "revenue_yoy": snap.revenue_yoy,
            "net_profit": snap.net_profit,
            "net_profit_yoy": snap.net_profit_yoy,
            # gross_margin 部分标的指标表无此字段，为 0.0 时 coverage<1.0
            "gross_margin": snap.gross_margin if snap.gross_margin != 0.0 else None,
            # operating_cf 为每股经营性现金流（元/股），非总额；标注来源
            "operating_cf": snap.operating_cf if snap.operating_cf != 0.0 else None,
            "operating_cf_per_share": snap.operating_cf if snap.operating_cf != 0.0 else None,
            "operating_cf_unit": "yuan_per_share",
            "debt_ratio": snap.debt_ratio if snap.debt_ratio != 0.0 else None,
            "roe": snap.roe if snap.roe != 0.0 else None,
            "coverage": snap.coverage,
            "source": snap.source,
        }


async def _cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()
    probe = FinancialProbe()
    result: ProbeResult = await probe.fetch(args.symbol)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_cli())
