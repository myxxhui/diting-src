"""D1 cryo_guard step02 数据量进度快照（只读）.

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_02 §7.2 cryo-step02-status]
"""

import os
import sqlite3

QUERIES = [
    ("financial_reports 总行数", "SELECT COUNT(*) FROM financial_reports"),
    ("financial_reports.industry 非null", "SELECT COUNT(*) FROM financial_reports WHERE industry IS NOT NULL"),
    ("announcements 总行数", "SELECT COUNT(*) FROM announcements"),
    ("announcements.content 非空(>200字)", "SELECT COUNT(*) FROM announcements WHERE LENGTH(content) > 200"),
    ("related_party_raw 总行数", "SELECT COUNT(*) FROM related_party_raw"),
    ("related_party_raw.pricing_method 非null", "SELECT COUNT(*) FROM related_party_raw WHERE pricing_method IS NOT NULL"),
    ("related_party_graph 总行数", "SELECT COUNT(*) FROM related_party_graph"),
    ("failed_ocr_pages 总行数", "SELECT COUNT(*) FROM failed_ocr_pages"),
]

THRESHOLDS = {
    "financial_reports 总行数": ("≥ 64", 64),
    "financial_reports.industry 非null": ("≥ 4", 4),
    "announcements 总行数": ("≥ 30", 30),
    "related_party_raw 总行数": ("≥ 50", 50),
    "related_party_graph 总行数": ("≥ 8", 8),
}


def main() -> None:
    db = os.environ.get("CRYO_DB_PATH", "data/cryo_guard.db")
    print(f"  DB: {db}  存在: {os.path.exists(db)}")
    if not os.path.exists(db):
        print("  ⚠️  DB 未创建，请先执行 make cryo-step02-prep")
        return

    conn = sqlite3.connect(db)
    print()
    for label, query in QUERIES:
        try:
            n = conn.execute(query).fetchone()[0]
            threshold = THRESHOLDS.get(label)
            if threshold:
                ok = n >= threshold[1]
                status = "✅" if ok else "⚠️ "
                print(f"  {status} {label}: {n}  （目标 {threshold[0]}）")
            else:
                print(f"     {label}: {n}")
        except sqlite3.OperationalError as e:
            print(f"  ⚠️  {label}: 表不存在（{e}）")
    conn.close()

    # Holdout 文件数
    holdout_dir = "training/data/holdout"
    if os.path.isdir(holdout_dir):
        h_count = len([f for f in os.listdir(holdout_dir) if f.startswith("H") and f.endswith(".json")])
        status = "✅" if h_count == 50 else "⚠️ "
        print(f"\n  {status} Holdout H*.json: {h_count}  （目标 = 50）")
    else:
        print(f"\n  ⚠️  Holdout 目录不存在：{holdout_dir}")


if __name__ == "__main__":
    main()
