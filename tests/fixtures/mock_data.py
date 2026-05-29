"""deep_strike 测试用 mock 构造。[Ref: step_03 证据链]"""


def build_mock_peers(symbol: str) -> list[dict]:
    """3 个同业 + 各自最新毛利率快照（与 L3 一致）。"""
    peers = [
        ("000333", "美的集团", 0.24),
        ("000651", "格力电器", 0.26),
        ("000100", "TCL科技", 0.18),
    ]
    return [
        {
            "symbol": symbol,
            "industry_code": "BK0428",
            "industry_name": "白色家电",
            "peer_symbol": p[0],
            "peer_name": p[1],
            "peer_metric_snapshot": {"gross_margin": p[2]},
        }
        for p in peers
    ]
