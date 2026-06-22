"""迁移：为已有 stock_pool_json 但缺少 version: "2.0" 的记录补上版本号。

修复根因：旧版 infer_ecosystem_stock_pool 返回结果中缺少 version 字段，
导致 _render_ecosystem_result 走到 v1.0 兜底路径（空概念标的池）。

运行方式：python scripts/migrations/20260623_fix_stock_pool_version.py
"""
import sys
import json

sys.path.insert(0, ".")

from apps.common.env import prepare_env
prepare_env()

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# 从环境变量或默认值获取 DSN
import os
dsn = os.getenv("COPILOT_PG_DSN", "postgresql://copilot:copilot@localhost:5432/copilot")
engine = create_engine(dsn)

fixed = 0
skipped = 0
error_count = 0

with Session(engine) as session:
    rows = session.execute(
        text("SELECT id, stock_pool_json FROM strategic_boards WHERE stock_pool_json IS NOT NULL")
    ).fetchall()

    for row in rows:
        board_id, spj_raw = row
        try:
            spj = spj_raw if isinstance(spj_raw, dict) else json.loads(spj_raw)
        except (json.JSONDecodeError, TypeError):
            error_count += 1
            continue

        if not isinstance(spj, dict):
            skipped += 1
            continue

        # 已有 version 2.0 或状态不是 ok → 跳过
        if spj.get("version") == "2.0":
            skipped += 1
            continue
        if spj.get("status") != "ok":
            skipped += 1
            continue

        # 有 bom_nodes 但缺 version → 补上
        if spj.get("bom_nodes"):
            spj["version"] = "2.0"
            spj["bom_whitelist_version"] = spj.get("bom_whitelist_version", "2.0.0")
            session.execute(
                text("UPDATE strategic_boards SET stock_pool_json = :spj WHERE id = :id"),
                {"spj": json.dumps(spj, ensure_ascii=False), "id": board_id},
            )
            fixed += 1
        else:
            skipped += 1

    session.commit()

print(f"迁移完成：fixed={fixed}, skipped={skipped}, error={error_count}")
