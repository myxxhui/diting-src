#!/usr/bin/env python3
"""
四区漏斗业务表清空脚本。

目的：清空四区漏斗（行情雷达/规划/执行/路线图）的脏数据，并从 holdings_sot 重新导入持仓。
持仓真相源（holdings_sot）是 YAML 文件，不是数据库表，天然不受影响。

[Ref: 25_四区漏斗_三段流水线_架构脊柱_设计.md]
[Ref: dna_stage_1_启动期.yaml#workflow_stages]
"""
import asyncio
import sys
from typing import Any

# PYTHONPATH 设置，允许 `PYTHONPATH=. python3 scripts/copilot_funnel_cleanup.py` 运行
sys.path.insert(0, ".")

from sqlalchemy import text

from apps.copilot.db.database import AsyncSessionLocal, engine, init_db
from apps.copilot.modules.planning.service import import_portfolio_to_campaign


# 待清空的表列表（与业务模型一一对应）
TABLES_TO_CLEANUP = [
    "campaigns",
    "campaign_symbols",
    "campaign_nodes",
    "campaign_timeline",
    "monitor_subscriptions",
    "execution_advices",
    "stage_artifacts",
    "workspace_artifacts",
    "radar_scans",
    "radar_candidates",
    "regime_assessments",
]


async def count_table_rows(session: Any, table_name: str) -> int:
    """查询表行数。表不存在时返回 0。"""
    try:
        result = await session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
        return result.scalar() or 0
    except Exception:
        return 0


async def delete_table_rows(session: Any, table_name: str) -> bool:
    """清空表。成功返回 True，表不存在或出错返回 False。"""
    try:
        await session.execute(text(f"DELETE FROM {table_name}"))
        await session.commit()
        return True
    except Exception as e:
        await session.rollback()
        return False


async def main() -> None:
    """主函数：初始化 → 统计前 → 清空 → 统计后 → 重新导入。"""
    print("[四区漏斗数据清空]")
    print()

    # 1. 初始化数据库表结构
    print("初始化数据库表结构…")
    await init_db()
    print("✓ 数据库就绪")
    print()

    # 2. 获取会话
    async with AsyncSessionLocal() as session:
        # 3. 统计清空前的行数
        print("【清空前行数统计】")
        before_counts: dict[str, int] = {}
        for table in TABLES_TO_CLEANUP:
            count = await count_table_rows(session, table)
            before_counts[table] = count
            if count > 0:
                print(f"  {table}: {count} 行")
            else:
                print(f"  {table}: 0 行 (空)")
        print()

        # 4. 清空各表
        print("【开始清空表…】")
        cleaned_tables = []
        skipped_tables = []
        for table in TABLES_TO_CLEANUP:
            success = await delete_table_rows(session, table)
            if success:
                cleaned_tables.append(table)
                print(f"  ✓ {table} 已清空")
            else:
                skipped_tables.append(table)
                print(f"  ⚠ {table} 跳过 (表不存在或出错)")
        print()

        if skipped_tables:
            print(f"跳过的表：{', '.join(skipped_tables)}")
            print()

        # 5. 统计清空后的行数
        print("【清空后行数统计】")
        after_counts: dict[str, int] = {}
        for table in TABLES_TO_CLEANUP:
            count = await count_table_rows(session, table)
            after_counts[table] = count
            if count > 0:
                print(f"  {table}: {count} 行")
            else:
                print(f"  {table}: 0 行 ✓")
        print()

        # 6. 对比清空前后
        print("【行数对比】")
        total_before = sum(before_counts.values())
        total_after = sum(after_counts.values())
        deleted_rows = total_before - total_after
        print(f"  清空前总计：{total_before} 行")
        print(f"  清空后总计：{total_after} 行")
        print(f"  删除行数：{deleted_rows} 行")
        print()

        # 7. 重新导入持仓
        print("【重新导入持仓…】")
        try:
            # 尝试使用 fakeredis
            try:
                import fakeredis

                fake_redis_client = fakeredis.FakeRedis(decode_responses=True)
                print("  使用 fakeredis 作为 Redis 客户端…")
            except ImportError:
                print("  ⚠ fakeredis 不可用，尝试不传 redis_client…")
                fake_redis_client = None

            # 调用导入函数
            if fake_redis_client is not None:
                result = await import_portfolio_to_campaign(session, redis_client=fake_redis_client)
            else:
                result = await import_portfolio_to_campaign(session, redis_client=None)

            imported_count = result.get("imported_count", 0)
            total_symbols = result.get("total_symbols", 0)
            print(f"  ✓ 重新导入成功")
            print(f"    - 新增标的数：{imported_count}")
            print(f"    - 总标的数：{total_symbols}")
            print(f"    - 源：{result.get('source', '未知')}")
            print()
        except Exception as e:
            print(f"  ⚠ 重新导入跳过：{type(e).__name__}: {str(e)}")
            print(f"  → 应用下次启动会自动导入")
            print()

    print("【完成】四区漏斗数据清空脚本执行完毕")
    return


if __name__ == "__main__":
    asyncio.run(main())
