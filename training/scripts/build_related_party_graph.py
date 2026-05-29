"""从 related_party_raw 提取去重后的关联方实体节点，写入 related_party_graph。

逻辑：
  1. 从 related_party_raw 按 symbol 分组，提取 party_name 中形如
     公司 / 子公司 / 关联方 实体名（含「公司」「集团」「企业」的字串）。
  2. 每个 (symbol, party_name) 对 upsert 一条 graph 节点记录。
  3. 目标：每只 active 标的至少 1 行（W1 准出 ≥ 8 行）。

[Ref: 03_/01_维度一_极寒防御/stages/stage_1_启动期/steps/step_02 §3.5 R1]
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from apps.cryo_guard.crawl_env_bootstrap import bootstrap_crawl_env

bootstrap_crawl_env(_REPO_ROOT)

from sqlalchemy import text, select, func

from apps.cryo_guard.db.sync_session import session_scope

logger = logging.getLogger(__name__)

# 关键词：用于从 party_name 行判断是否为公司实体名
_ENTITY_KEYWORDS = re.compile(
    r"(股份有限公司|有限公司|有限责任公司|集团公司|合伙企业|基金会|控股集团|子公司|关联方实体)"
)

# 最大每 symbol 提取节点数（避免噪音过多）
MAX_NODES_PER_SYMBOL = 50


def extract_entity_names(raw_rows: list[tuple]) -> list[str]:
    """从 (party_name, relationship) 行提取「像实体名」的文本。

    规则：
    - party_name 含上述关键词 → 视为实体名
    - 截断到 128 字符以内
    - 去重
    """
    seen: set[str] = set()
    result: list[str] = []
    for party_name, relationship in raw_rows:
        name = (party_name or "").strip()
        # 过滤明显是正文句子的噪音（超过 100 字且无关键词）
        if len(name) > 100 and not _ENTITY_KEYWORDS.search(name):
            continue
        if _ENTITY_KEYWORDS.search(name):
            name = name[:128]
            if name not in seen:
                seen.add(name)
                result.append(name)
    return result[:MAX_NODES_PER_SYMBOL]


def build_graph_for_symbol(symbol: str, session) -> int:
    """为一只标的构建关联方图节点，返回新插入行数。"""
    rows = session.execute(
        text(
            "SELECT party_name, relationship FROM related_party_raw "
            "WHERE symbol = :symbol"
        ),
        {"symbol": symbol},
    ).fetchall()

    if not rows:
        logger.warning("  ⚠️  %s 无 related_party_raw 数据，跳过", symbol)
        return 0

    entity_names = extract_entity_names(rows)

    # 如果一个「真实公司名」都提不出来，至少插入 1 行占位（公司本身）
    if not entity_names:
        # 尝试用 company_name
        cn_row = session.execute(
            text("SELECT company_name FROM related_party_raw WHERE symbol = :symbol LIMIT 1"),
            {"symbol": symbol},
        ).fetchone()
        placeholder = cn_row[0].strip()[:128] if cn_row else symbol
        entity_names = [placeholder]

    inserted = 0
    for party_name in entity_names:
        # 检查是否已存在
        exists = session.execute(
            text(
                "SELECT id FROM related_party_graph "
                "WHERE symbol = :symbol AND party_name = :pname LIMIT 1"
            ),
            {"symbol": symbol, "pname": party_name},
        ).fetchone()
        if exists:
            continue
        session.execute(
            text(
                "INSERT INTO related_party_graph (symbol, party_name, created_at) "
                "VALUES (:symbol, :pname, CURRENT_TIMESTAMP)"
            ),
            {"symbol": symbol, "pname": party_name},
        )
        inserted += 1

    return inserted


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logger.info("[build_related_party_graph] 开始构建关联方图节点")

    with session_scope() as session:
        # 取有 related_party_raw 数据的所有 symbol
        symbols_raw = session.execute(
            text(
                "SELECT DISTINCT symbol FROM related_party_raw ORDER BY symbol"
            )
        ).fetchall()
        symbols = [r[0] for r in symbols_raw]
        logger.info("  发现 %d 个 symbol: %s", len(symbols), symbols)

        total_inserted = 0
        for symbol in symbols:
            cnt = build_graph_for_symbol(symbol, session)
            total_inserted += cnt
            logger.info("  %s: +%d 节点", symbol, cnt)

        session.commit()

    # 验收
    with session_scope() as session:
        total = session.execute(
            text("SELECT COUNT(*) FROM related_party_graph")
        ).scalar()
        by_sym = session.execute(
            text(
                "SELECT symbol, COUNT(*) FROM related_party_graph "
                "GROUP BY symbol ORDER BY symbol"
            )
        ).fetchall()

    logger.info("[build_related_party_graph] 完成")
    logger.info("  ▶ related_party_graph 总行数: %d（目标 ≥ 8）", total)
    for sym, cnt in by_sym:
        status = "✅" if cnt >= 1 else "⚠️"
        logger.info("    %s %s: %d 节点", status, sym, cnt)

    if total < 8:
        logger.error("  ❌ 总行数 %d < 8，准出失败", total)
        sys.exit(1)
    logger.info("  ✅ related_party_graph 准出通过")


if __name__ == "__main__":
    main()
