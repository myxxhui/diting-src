#!/usr/bin/env python3
"""
概念板块自动同步脚本 · 每日/每周拉取同花顺概念列表
更新 z0_policy_keywords.yaml 中 child_concepts 的 code/name
[Ref: z0_policy_keywords.yaml v2.0 · §concept_sync]
"""
import sys
import yaml
import asyncio
from pathlib import Path
from datetime import datetime

KEYWORDS_PATH = (
    Path(__file__).resolve().parents[2]
    / "data" / "config" / "metrics" / "z0_policy_keywords.yaml"
)


def fetch_ths_concepts() -> dict[str, str]:
    """拉取同花顺全部概念板块列表 → {概念代码: 概念名称}"""
    try:
        import akshare as ak
        df = ak.stock_board_concept_name_ths()
        return {str(row["code"]): str(row["name"]) for _, row in df.iterrows()}
    except ImportError:
        print("[ERROR] akshare 未安装或网络不可用", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"[ERROR] 同花顺概念拉取失败: {e}", file=sys.stderr)
        return {}


def scan_mapping_diff(
    yaml_data: dict, ths_map: dict[str, str]
) -> list[dict]:
    """对比现有映射表与实时概念列表，输出差异报告。"""
    diffs = []
    canonical_sectors = yaml_data.get("canonical_sectors") or {}
    for sector_name, sector_cfg in canonical_sectors.items():
        # 主概念 code
        main_code = sector_cfg.get("concept_code")
        if main_code and main_code in ths_map:
            ths_name = ths_map[main_code]
            if sector_cfg.get("concept_name") != ths_name:
                diffs.append({
                    "type": "rename_concept",
                    "sector": sector_name,
                    "code": main_code,
                    "old_name": sector_cfg.get("concept_name"),
                    "new_name": ths_name,
                    "action": "auto_update",
                })
        elif main_code:
            diffs.append({
                "type": "delisted_concept",
                "sector": sector_name,
                "code": main_code,
                "old_name": sector_cfg.get("concept_name"),
                "action": "manual_review",
            })

        # 子概念 codes
        child_concepts = sector_cfg.get("child_concepts") or []
        for cc in child_concepts:
            cc_code = cc.get("code")
            if cc_code and cc_code in ths_map:
                ths_name = ths_map[cc_code]
                if cc.get("name") != ths_name:
                    diffs.append({
                        "type": "rename_subconcept",
                        "sector": sector_name,
                        "code": cc_code,
                        "old_name": cc.get("name"),
                        "new_name": ths_name,
                        "action": "auto_update",
                    })
            elif cc_code:
                diffs.append({
                    "type": "delisted_subconcept",
                    "sector": sector_name,
                    "code": cc_code,
                    "old_name": cc.get("name"),
                    "action": "manual_review",
                })
    return diffs


def apply_diffs(yaml_data: dict, diffs: list[dict]) -> dict:
    """应用自动更新（只改名称，不改 code）。"""
    canonical_sectors = yaml_data.setdefault("canonical_sectors", {})
    for d in diffs:
        if d["action"] != "auto_update":
            continue
        sector = d["sector"]
        code = d["code"]
        new_name = d["new_name"]
        if d["type"] == "rename_concept":
            if sector in canonical_sectors:
                canonical_sectors[sector]["concept_name"] = new_name
        elif d["type"] == "rename_subconcept":
            if sector in canonical_sectors:
                for cc in canonical_sectors[sector].get("child_concepts") or []:
                    if cc.get("code") == code:
                        cc["name"] = new_name
    yaml_data.setdefault("concept_sync", {})["last_synced_at"] = datetime.utcnow().isoformat()
    return yaml_data


async def async_main(*, apply: bool = False):
    """异步主入口。"""
    # 1. 读取当前配置
    if not KEYWORDS_PATH.exists():
        print(f"[ERROR] keywords 文件不存在: {KEYWORDS_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(KEYWORDS_PATH, "r", encoding="utf-8") as f:
        yaml_data = yaml.safe_load(f)

    cfg = yaml_data.get("concept_sync") or {}
    if not cfg.get("enabled"):
        print("[INFO] concept_sync 未启用（enabled: false），跳过。")
        return

    # 2. 拉取实时概念列表
    print("[INFO] 正在拉取同花顺概念列表...")
    ths_map = fetch_ths_concepts()
    if not ths_map:
        print("[ERROR] 无概念数据，退出。", file=sys.stderr)
        sys.exit(1)
    print(f"[INFO] 获取到 {len(ths_map)} 个概念板块")

    # 3. 差异扫描
    diffs = scan_mapping_diff(yaml_data, ths_map)
    if not diffs:
        print("[INFO] ✅ 概念映射表与实时数据一致，无需更新。")
        return

    # 4. 输出报告
    print(f"\n{'='*60}")
    print(f"[REPORT] 发现 {len(diffs)} 处差异")
    print(f"{'='*60}")
    auto_updates = [d for d in diffs if d["action"] == "auto_update"]
    manual_reviews = [d for d in diffs if d["action"] == "manual_review"]

    if auto_updates:
        print(f"\n🟢 自动更新 ({len(auto_updates)} 项)：")
        for d in auto_updates:
            print(f"  [{d['sector']}] {d['code']} 「{d.get('old_name')}」→「{d['new_name']}」")
    if manual_reviews:
        print(f"\n🔴 需人工复核 ({len(manual_reviews)} 项)：")
        for d in manual_reviews:
            print(f"  [{d['sector']}] {d['code']} 「{d.get('old_name')}」已下架/不存在，手动判断是否保留")

    # 5. 应用更新
    if apply:
        updated = apply_diffs(yaml_data, diffs)
        with open(KEYWORDS_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(updated, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        print(f"\n[INFO] ✅ 已写入 {KEYWORDS_PATH}")
    else:
        print(f"\n[INFO] 仅输出差异报告（未写入）。若要自动写入，加 --apply 参数。")

    print(f"\n{'='*60}")
    print(f"[DONE] {datetime.now().isoformat()}")
    print(f"{'='*60}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="同花顺概念板块同步脚本")
    parser.add_argument("--apply", action="store_true", help="自动写入更新到 keywords.yaml")
    args = parser.parse_args()
    asyncio.run(async_main(apply=args.apply))


if __name__ == "__main__":
    main()
