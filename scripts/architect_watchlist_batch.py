#!/usr/bin/env python3
"""为 6 只 watchlist 批量运行 Architect，生成监控字典写入 Redis。

6 只 watchlist（W3 Opus 范围）：
  - 600312 平高电气   电力基建
  - 300308 中际旭创   光模块/CPO
  - 300502 新易盛     光模块/CPO
  - 002837 英维克     散热/液冷
  - 300499 高澜股份   散热/液冷
  - 300602 飞荣达     散热/液冷

预算控制：6 只 × 1 次 Architect ≈ ¥3～6

[Ref: 03_/02_维度二/.../step_02 §3.5.5 The Architect]
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path


def _load_dotenv() -> None:
    env_file = Path(__file__).parents[1] / ".env"
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


WATCHLIST_CONFIGS = [
    {
        "symbol": "600312",
        "name": "平高电气",
        "segment": "电力基建",
        "logic_chain_nodes": [
            "node_grid_investment_cycle",
            "node_uhv_equipment_demand",
            "node_switchgear_order_backlog",
        ],
    },
    {
        "symbol": "300308",
        "name": "中际旭创",
        "segment": "光模块/CPO",
        "logic_chain_nodes": [
            "node_ai_datacenter_capex",
            "node_optical_transceiver_demand",
            "node_800g_1.6t_upgrade_cycle",
        ],
    },
    {
        "symbol": "300502",
        "name": "新易盛",
        "segment": "光模块/CPO",
        "logic_chain_nodes": [
            "node_ai_datacenter_capex",
            "node_optical_transceiver_demand",
            "node_north_america_hyperscaler_orders",
        ],
    },
    {
        "symbol": "002837",
        "name": "英维克",
        "segment": "散热/液冷",
        "logic_chain_nodes": [
            "node_liquid_cooling_penetration",
            "node_datacenter_pue_regulation",
            "node_capacity_expansion_progress",
        ],
    },
    {
        "symbol": "300499",
        "name": "高澜股份",
        "segment": "散热/液冷",
        "logic_chain_nodes": [
            "node_liquid_cooling_penetration",
            "node_power_electronics_cooling",
            "node_industrial_cooling_orders",
        ],
    },
    {
        "symbol": "300602",
        "name": "飞荣达",
        "segment": "散热/液冷",
        "logic_chain_nodes": [
            "node_thermal_management_demand",
            "node_emi_shielding_materials",
            "node_ai_server_thermal_solution",
        ],
    },
]


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Architect 批量执行 / 重跑 watchlist 监控字典")
    parser.add_argument(
        "--symbols",
        default="",
        help="指定 symbol 列表（逗号分隔，如 '002837,300499,300502'）；缺省跑全部 6 只",
    )
    args = parser.parse_args()

    _load_dotenv()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("⚠️  ANTHROPIC_API_KEY 未配置，跳过 Architect 批量执行")
        return 0

    requested: set[str] = {s.strip() for s in args.symbols.split(",") if s.strip()}
    configs = WATCHLIST_CONFIGS if not requested else [
        c for c in WATCHLIST_CONFIGS if c["symbol"] in requested
    ]
    if not configs:
        print(f"⚠️  --symbols={args.symbols!r} 未匹配 watchlist 中任意标的")
        return 1

    # Redis 连接（使用 super-evo-redis 的 db5）
    redis_url = os.getenv("SUPER_EVO_REDIS_URL", "redis://localhost:6379/5")
    print(f"  REDIS_URL = {redis_url}")

    import redis
    redis_client = redis.from_url(redis_url, decode_responses=True)
    try:
        redis_client.ping()
        print("  Redis 连接 ✅")
    except redis.ConnectionError as e:
        print(f"⚠️  Redis 连接失败: {e}")
        return 1

    from apps.common.ai_dispatcher import AIDispatcher
    AIDispatcher._instance = None
    dispatcher = AIDispatcher.default()
    print(f"  budget 状态: {dispatcher.budget_status()}")

    from apps.deep_strike.lighthouse import TheArchitect
    from apps.deep_strike.lighthouse.schemas import ArchitectInput
    from apps.deep_strike.lighthouse.monitor_dict_writer import MonitorDictWriter

    architect = TheArchitect(dispatcher=dispatcher)
    writer = MonitorDictWriter(redis_client)

    print("\n" + "=" * 70)
    n = len(configs)
    print(f"  Architect 批量执行（{n} 只 watchlist）")
    print("=" * 70)

    today = date.today().strftime("%Y%m%d")
    results = []

    for i, cfg in enumerate(configs, 1):
        symbol = cfg["symbol"]
        name = cfg["name"]
        segment = cfg["segment"]
        nodes = cfg["logic_chain_nodes"]

        print(f"\n[{i}/{n}] {symbol} {name}（{segment}）...")

        thesis_card_id = f"thesis_{symbol}_{segment.replace('/', '_')}_{today}"
        try:
            arch_out = architect.call(ArchitectInput(
                thesis_card_id=thesis_card_id,
                target_company=name,
                symbol=symbol,
                logic_chain_nodes=nodes,
            ))
            print(f"  monitor 字段数: {len(arch_out.monitor_matrix)}")
            for f in arch_out.monitor_matrix[:2]:
                print(f"    - {f.probe_id} {f.metric_name[:40]}")

            # 写入 Redis
            write_result = writer.write(arch_out)
            print(f"  Redis 写入: {write_result['written']} 个字段")
            if write_result["rejected"]:
                print(f"  ⚠️  拒绝: {write_result['rejected']}")

            results.append({
                "symbol": symbol,
                "name": name,
                "status": "ok",
                "fields_written": len(write_result["written"]),
                "fields_rejected": len(write_result["rejected"]),
            })

        except Exception as exc:
            print(f"  ❌ 失败: {exc}")
            results.append({
                "symbol": symbol,
                "name": name,
                "status": "error",
                "error": str(exc)[:100],
            })

    # 总结
    final_budget = dispatcher.budget_status()
    ok_count = sum(1 for r in results if r["status"] == "ok")
    total_fields = sum(r.get("fields_written", 0) for r in results)

    print("\n" + "=" * 70)
    print(f"  ✅ Architect 完成: {ok_count}/{n} 成功，共写入 {total_fields} 个监控字段")
    print(f"  预算消耗 ≈ ¥{final_budget['spent_yuan']:.2f}")
    print("=" * 70)

    # 验证 Redis 中的 key（仅本次执行范围）
    print("\n  Redis 监控字典 key 列表:")
    for cfg in configs:
        symbol = cfg["symbol"]
        keys = redis_client.keys(f"monitor:{symbol}:dict:*")
        print(f"    {symbol}: {len(keys)} 个 key")

    return 0 if ok_count == n else 1


if __name__ == "__main__":
    sys.exit(main())
