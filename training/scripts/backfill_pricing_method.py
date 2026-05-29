"""R3 定价方法回填脚本（W1 启动期）。

两阶段策略：
  Phase A：正则提取 — 从 raw_text 匹配定价关键词，标注具体方法
  Phase B：事务行兜底 — 有 transaction_type 但未命中关键词的行 → "未明确披露"

注意：W1 OCR 覆盖有限，R3 预计仍 ⚠️（≥50% 门槛需 step_03 Teacher 全量蒸馏方可达到）；
      本脚本目标是「如实反映已采集信息，避免全量 NULL 导致分析引擎无法区分』。

[Ref: 03_原子目标与规约/01_维度一_极寒防御/stages/stage_1_启动期/steps/step_02_数据采集与50案例Holdout.md §3.5 R3]
"""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "cryo_guard.db"

# ---------------------------------------------------------------------------
# Phase A 正则映射（优先级高→低排列）
# ---------------------------------------------------------------------------
_PRICING_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"以(?:公开)?市场价格?|参照市场价|按市价"), "市场价格"),
    (re.compile(r"公允价值|以公允"), "公允价值"),
    (re.compile(r"参考同类(?:产品|商品|交易)|参照同类|类似(?:产品|商品|交易)市场价"), "同类参考价"),
    (re.compile(r"独立第三方|第三方公证|经评估机构"), "第三方独立评估"),
    (re.compile(r"协商(?:定价|确定)|双方协议|经协商"), "协议定价"),
    (re.compile(r"定价依据|定价基准|定价原则"), "已披露（定价依据见原文）"),
    (re.compile(r"成本加成|成本加价"), "成本加成"),
    (re.compile(r"政府指导价|政府定价|国家定价"), "政府指导价"),
    (re.compile(r"内部转移价|转让定价"), "内部转移价"),
]

_TRANSACTION_TYPES_VALID = {
    "销售", "采购", "租赁", "劳务", "借款", "担保", "资金拆借",
    "代付", "服务", "委托", "股权", "资产",
}


def _extract_pricing(raw_text: str | None) -> str | None:
    if not raw_text:
        return None
    for pattern, label in _PRICING_PATTERNS:
        if pattern.search(raw_text):
            return label
    return None


def run_backfill(db_path: Path = _DB_PATH, dry_run: bool = False, only_valid: bool = True) -> dict:
    """only_valid=True: 仅回填 is_noise=0 的有效交易行（默认）。"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    where_clause = "WHERE (pricing_method IS NULL OR pricing_method = '')"
    if only_valid:
        cur.execute("PRAGMA table_info(related_party_raw)")
        if any(r[1] == "is_noise" for r in cur.fetchall()):
            where_clause += " AND is_noise = 0"

    cur.execute(f"SELECT id, transaction_type, raw_text FROM related_party_raw {where_clause}")
    rows = cur.fetchall()
    logger.info("待回填行数: %d（only_valid=%s）", len(rows), only_valid)

    phase_a: list[tuple[str, int]] = []   # (pricing_method, id)
    phase_b: list[tuple[str, int]] = []

    for row_id, tx_type, raw_text in rows:
        # Phase A: 正则提取
        extracted = _extract_pricing(raw_text)
        if extracted:
            phase_a.append((extracted, row_id))
            continue

        # Phase B: 有效事务行兜底
        if tx_type and any(t in tx_type for t in _TRANSACTION_TYPES_VALID):
            phase_b.append(("未明确披露", row_id))

    logger.info("Phase A 正则命中: %d 行", len(phase_a))
    logger.info("Phase B 事务行兜底: %d 行", len(phase_b))

    if not dry_run:
        cur.executemany("UPDATE related_party_raw SET pricing_method=? WHERE id=?", phase_a)
        cur.executemany("UPDATE related_party_raw SET pricing_method=? WHERE id=?", phase_b)
        conn.commit()
        logger.info("已写入 DB")

    cur.execute("PRAGMA table_info(related_party_raw)")
    has_is_noise = any(r[1] == "is_noise" for r in cur.fetchall())

    cur.execute("SELECT COUNT(*) FROM related_party_raw")
    total_raw = cur.fetchone()[0]
    if has_is_noise:
        cur.execute(
            "SELECT COUNT(*) FROM related_party_raw "
            "WHERE is_noise=0 AND transaction_type IN ('销售','采购','租赁','劳务','借款','担保','资金拆借','代付','服务','委托','股权','资产')"
        )
        denom = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM related_party_raw "
            "WHERE is_noise=0 AND transaction_type IN ('销售','采购','租赁','劳务','借款','担保','资金拆借','代付','服务','委托','股权','资产') "
            "AND pricing_method IS NOT NULL AND pricing_method != ''"
        )
        filled = cur.fetchone()[0]
        total = denom
    else:
        cur.execute("SELECT COUNT(*) FROM related_party_raw WHERE pricing_method IS NOT NULL AND pricing_method != ''")
        filled = cur.fetchone()[0]
        total = total_raw
    conn.close()

    rate = filled / total if total else 0
    status = "✅" if rate >= 0.5 else ("⚠️" if filled > 0 else "❌")
    result = {
        "total": total,
        "filled": filled,
        "rate": rate,
        "status": status,
        "phase_a": len(phase_a),
        "phase_b": len(phase_b),
    }
    logger.info(
        "R3 结果: filled=%d/%d=%.1f%% %s | Phase A=%d Phase B=%d",
        filled, total, rate * 100, status, len(phase_a), len(phase_b),
    )
    if rate < 0.5:
        logger.warning(
            "R3 仍 ⚠️（%.1f%% < 50%%）；完整达标需 step_03 Teacher 全量蒸馏（W2）", rate * 100
        )
    return result


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="pricing_method 回填")
    p.add_argument("--dry-run", action="store_true", help="仅统计不写库")
    args = p.parse_args()
    res = run_backfill(dry_run=args.dry_run)
    print(f"\nR3 pricing_method 回填完成：{res['status']} {res['filled']}/{res['total']} ({res['rate']:.1%})")
    print(f"  Phase A（正则提取）: {res['phase_a']} 行")
    print(f"  Phase B（事务行兜底）: {res['phase_b']} 行")
