"""批量对所有持仓评估指定协议(本地手工验证)。

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_03_SP1止损协议.md]
[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_04_SP2止盈协议.md]

usage:
  python scripts/evaluate_all_holdings.py --protocol stop_loss
  python scripts/evaluate_all_holdings.py --protocol take_profit --user-id default --mock-price
"""
from __future__ import annotations

import argparse
import sys

from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.data.mock_quote_fetcher import MockQuoteFetcher
from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.protocols.stop_loss import StopLossProtocol
from apps.exit_engine.protocols.take_profit import TakeProfitProtocol
from apps.exit_engine.services.protocol_runner import evaluate_and_audit, evaluate_with_buffer

PROTOCOL_BY_NAME = {
    "stop_loss": StopLossProtocol,
    "take_profit": TakeProfitProtocol,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", required=True, choices=list(PROTOCOL_BY_NAME))
    parser.add_argument("--user-id", default="default")
    parser.add_argument("--mock-price", action="store_true", help="使用 mock fixture 注入 current_price")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        repo = HoldingsRepository(session)
        positions = repo.list_active(user_id=args.user_id)
        if args.mock_price:
            fetcher = MockQuoteFetcher()
            quotes = fetcher.fetch_batch([p.symbol for p in positions])
            repo.bulk_update_quotes(quotes, user_id=args.user_id)
            positions = repo.list_active(user_id=args.user_id)

        protocol = PROTOCOL_BY_NAME[args.protocol]()
        triggered_count = 0
        for pos in positions:
            if args.protocol == "take_profit":
                result = evaluate_with_buffer(protocol, pos, session=session, user_id=args.user_id)
            else:
                result = evaluate_and_audit(protocol, pos, session=session, user_id=args.user_id)

            extra = ""
            if args.protocol == "take_profit" and result.triggered and protocol.buffer_days > 0:
                if result.buffer_enqueued is True:
                    extra = " (buffer_pending)"
                elif result.buffer_enqueued is False:
                    extra = " (buffer_already_pending)"

            mark = "🟡" if extra else ("🔴" if result.triggered else "  ")
            rp = pos.return_pct if pos.return_pct is not None else 0.0
            cp = pos.current_price if pos.current_price is not None else float("nan")
            print(
                f"{mark} {pos.symbol} {pos.name:<8} cost={pos.cost_price:.2f} "
                f"price={cp} return={rp * 100:+.2f}% triggered={result.triggered}{extra}"
            )
            if result.triggered:
                triggered_count += 1
        print(f"\n✅ 完成 共 {len(positions)} 笔 触发 {triggered_count} 笔")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
