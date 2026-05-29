"""R1/R3 关联交易表去噪标注脚本（启动期金标准）。

策略：保留 raw 数据（便于回溯）；新增 `is_noise INTEGER DEFAULT 0` 列，对
PDF 碎片 / 报告元数据行 / 无业务字段行打标 is_noise=1。下游质量矩阵与
Teacher 蒸馏候选基于 `WHERE is_noise=0` 计算，让指标反映真实质量。

噪音判定（满足任一）：
  N1  party_name 含元数据词（年度/报告/合并/披露/摘要/...）
  N2  party_name 长度 > 80（整段 PDF 文本被当成 party）
  N3  transaction_type 与 amount 均为 null（无任何业务字段）
  N4  party_name 含括号说明但不含公司/企业/基金等实体词
  N5  party_name 含 PDF 页码/章节编号格式（如 "（6）"、"5、"）

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_02 §3.5 R1/R3]
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "cryo_guard.db"

VALID_TX_TYPES = {
    "销售", "采购", "租赁", "劳务", "借款", "担保", "资金拆借", "代付",
    "服务", "委托", "股权", "资产",
}

NOISE_META_WORDS = re.compile(
    r"(年度报告|报告期内|报告期末|合并范围|披露事项|信息披露|"
    r"重要提示|公司简介|目录|附录|附注|说明事项|本附注|表格说明|"
    r"单位[:：]|币种[:：]|金额单位)"
)

ENTITY_HINTS = re.compile(r"(公司|企业|基金|集团|银行|股份|有限|合伙|个人|自然人|境外法人)")

SECTION_NUMBER = re.compile(r"^\s*[（(]\s*[\d一二三四五六七八九十]+\s*[)）]|^\s*[\d]+\s*[、.]")


def _classify_noise(row_id: int, party_name: str | None, tx_type: str | None, amount: float | None) -> int:
    """返回 1 表示噪音，0 表示有效行（保守判定：宁可漏判也不误删）。"""
    if not party_name:
        return 1

    if tx_type and any(t in tx_type for t in VALID_TX_TYPES):
        if amount is not None and amount > 0:
            return 0
        if len(party_name) <= 60 and ENTITY_HINTS.search(party_name):
            return 0

    if NOISE_META_WORDS.search(party_name):
        return 1

    if len(party_name) > 80:
        return 1

    if SECTION_NUMBER.match(party_name):
        return 1

    if tx_type is None and amount is None and not ENTITY_HINTS.search(party_name):
        return 1

    if "（" in party_name and "）" in party_name and not ENTITY_HINTS.search(party_name):
        return 1

    return 0


def ensure_is_noise_column(conn: sqlite3.Connection) -> bool:
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(related_party_raw)")
    cols = {r[1] for r in cur.fetchall()}
    if "is_noise" in cols:
        return False
    logger.info("新增列 is_noise INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE related_party_raw ADD COLUMN is_noise INTEGER DEFAULT 0")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_rp_is_noise ON related_party_raw(is_noise)")
    conn.commit()
    return True


def run_clean(db_path: Path = _DB_PATH, dry_run: bool = False) -> dict:
    conn = sqlite3.connect(db_path)
    ensure_is_noise_column(conn)
    cur = conn.cursor()

    cur.execute("SELECT id, party_name, transaction_type, amount FROM related_party_raw")
    rows = cur.fetchall()
    logger.info("待评估行数: %d", len(rows))

    updates: list[tuple[int, int]] = []
    for row_id, party_name, tx_type, amount in rows:
        flag = _classify_noise(row_id, party_name, tx_type, amount)
        updates.append((flag, row_id))

    if not dry_run:
        cur.executemany("UPDATE related_party_raw SET is_noise=? WHERE id=?", updates)
        conn.commit()
        logger.info("写库完成")

    noise_cnt = sum(1 for f, _ in updates if f == 1)
    valid_cnt = len(updates) - noise_cnt

    cur.execute("SELECT COUNT(*) FROM related_party_raw WHERE is_noise=0 AND pricing_method IS NOT NULL AND pricing_method != ''")
    valid_with_pricing = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM related_party_raw WHERE is_noise=0 AND transaction_type IN ('销售','采购','租赁','劳务','借款','担保','资金拆借','代付')")
    valid_with_tx = cur.fetchone()[0]
    conn.close()

    r3_rate = (valid_with_pricing / valid_cnt) if valid_cnt else 0.0

    result = {
        "total": len(updates),
        "noise": noise_cnt,
        "valid": valid_cnt,
        "noise_rate": noise_cnt / len(updates) if updates else 0,
        "valid_with_tx_type": valid_with_tx,
        "valid_with_pricing": valid_with_pricing,
        "r3_rate_on_valid": r3_rate,
    }
    logger.info(
        "去噪结果: total=%d noise=%d (%.1f%%) valid=%d valid_with_tx=%d valid_with_pricing=%d R3@valid=%.1f%%",
        result["total"], result["noise"], result["noise_rate"] * 100, result["valid"],
        result["valid_with_tx_type"], result["valid_with_pricing"], r3_rate * 100,
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="关联交易噪音标注")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    res = run_clean(dry_run=args.dry_run)
    print(f"\n[去噪] 噪音 {res['noise']}/{res['total']} ({res['noise_rate']:.1%}); 有效 {res['valid']} (含交易类型 {res['valid_with_tx_type']}); R3@valid={res['r3_rate_on_valid']:.1%}")
