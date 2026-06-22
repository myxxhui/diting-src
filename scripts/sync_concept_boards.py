#!/usr/bin/env python3
"""
概念板块同步脚本 v5.1 · 同花顺概念全量对齐 + 差异处理 + 文档标签清理

行为：
  1. 拉取同花顺 373 个概念板块（akshare）
  2. 扫描 YAML child_concepts vs THS 实时数据，生成三类差异：
     - NEW：同花顺存在但 YAML 任何赛道都未收入 → 关键词匹配建议归属赛道
     - DELETED：YAML 中存在但同花顺已下线 → 从 YAML 移除 · 扫描清理 S0_doc 标签
     - RENAMED：code 相同但 name 变化 → 自动更新 YAML · 更新 S0_doc 标签
  3. 输出差异报告 + 应用自动变更
  4. 对新增概念：可触发 T1 重评分（--retag）让 LLM 重新选择概念

使用：
  python scripts/sync_concept_boards.py            # 仅输出差异报告
  python scripts/sync_concept_boards.py --apply    # 自动写入 YAML + 清理 DB 标签
  python scripts/sync_concept_boards.py --retag    # （TODO）触发 T1 重评分

[Ref: 36_ §5.5 · z0_policy_keywords.yaml · concept_sync]
"""

from __future__ import annotations

import json
import sys
import yaml
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 路径 ──────────────────────────────────────
_KEYWORDS_PATH = (
    Path(__file__).resolve().parents[2]
    / "data" / "config" / "metrics" / "z0_policy_keywords.yaml"
)

# 兼容容器内路径：diting-src → /app
if not _KEYWORDS_PATH.exists():
    _KEYWORDS_PATH = Path("/app/data/config/metrics/z0_policy_keywords.yaml")

logger = logging.getLogger(__name__)

# ── 赛道关键词映射（新概念自动归属） ─────────
_SECTOR_DISCOVERY_KEYWORDS: dict[str, list[str]] = {
    "AI算力": [
        "AI", "人工智能", "算力", "大模型", "芯片", "半导体", "光模块", "CPO",
        "液冷", "服务器", "先进封装", "机器人", "人形", "存储", "MCU",
        "数据中心", "智谱", "语料", "NPU", "GPU", "CoWoS", "HBM",
    ],
    "新能源": [
        "光伏", "储能", "锂电", "风电", "氢能", "充电桩", "钠离子",
        "固态电池", "新能源车", "绿色电力", "逆变器", "虚拟电厂", "特高压",
        "智能电网", "太阳能", "钙钛矿", "异质结", "TOPCon",
    ],
    "低空经济": [
        "低空", "无人机", "飞行汽车", "eVTOL", "通用航空", "商业航天",
        "卫星", "航天", "火箭",
    ],
    "数字经济": [
        "数据", "工业互联网", "物联网", "5G", "6G", "数字孪生", "信创",
        "数字货币", "区块链", "云计算", "边缘计算", "web3", "RPA", "SaaS",
    ],
    "医药创新": [
        "创新药", "生物医药", "合成生物", "医疗器械", "中药", "CXO",
        "细胞", "基因", "疫苗", "医美", "智慧医疗", "脑机", "CAR-T",
        "GLP", "ADC", "双抗", "mRNA",
    ],
    "消费内需": [
        "消费", "以旧换新", "跨境电商", "家电", "免税", "直播", "预制菜",
        "银发", "养老", "婴童", "宠物", "旅游", "酒店", "餐饮",
    ],
    "环保节能": [
        "碳中和", "碳达峰", "节能", "环保", "绿色", "碳交易", "碳配额",
        "建筑节能", "垃圾分类", "ESG", "污水处理", "CCUS", "固废",
    ],
    "基建交通": [
        "基建", "铁路", "公路", "港口", "水利", "交通", "物流", "地铁",
        "轨道交通", "工程机械", "水泥", "建筑", "冷链", "装配式",
    ],
    "金融国资": [
        "国资", "国企", "央企", "改革", "金融", "证券", "保险",
        "跨境支付", "数字货币", "资本市场", "科创板", "REITs", "AMC",
    ],
    "军工国防": [
        "军工", "国防", "军民融合", "导弹", "雷达", "北斗", "无人机",
        "航空发动机", "毫米波", "航天",
    ],
    "农业粮食": [
        "粮食", "种业", "农业", "乡村振兴", "猪肉", "化肥", "农药",
        "农机", "水产", "养殖", "转基因", "饲料",
    ],
    "新质生产力": [
        "新质生产力", "专精特新", "先进制造", "高端装备", "新材料",
        "量子", "人形机器人", "脑机接口", "6G", "可控核聚变",
    ],
}

# ══════════════════════════════════════════════════════════════
# Phase 1: 数据拉取
# ══════════════════════════════════════════════════════════════

def fetch_ths_concepts() -> dict[str, str]:
    """拉取同花顺全部概念板块 → {概念代码: 概念名称}。"""
    try:
        import akshare as ak
        df = ak.stock_board_concept_name_ths()
        return {str(row["code"]): str(row["name"]) for _, row in df.iterrows()}
    except ImportError:
        print("[ERROR] akshare 未安装", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"[ERROR] 同花顺概念拉取失败: {e}", file=sys.stderr)
        return {}


# ══════════════════════════════════════════════════════════════
# Phase 2: 差异扫描
# ══════════════════════════════════════════════════════════════

def _all_yaml_codes(yaml_data: dict) -> set[str]:
    """收集所有 YAML 中已配置的概念 code（跨赛道）。"""
    codes: set[str] = set()
    for sec_cfg in (yaml_data.get("canonical_sectors") or {}).values():
        for cc in (sec_cfg.get("child_concepts") or []):
            c = cc.get("code", "")
            if c:
                codes.add(str(c))
    return codes


def _classify_new_concept(name: str) -> list[tuple[str, float]]:
    """对同花顺中未归属的新概念，用关键词匹配推荐归属赛道。
    
    Returns: [(赛道名, 置信度), ...] 按置信度降序
    """
    scores: dict[str, float] = {}
    for sector, kws in _SECTOR_DISCOVERY_KEYWORDS.items():
        score = 0.0
        for kw in kws:
            if kw.lower() in name.lower():
                score += 1.0
        if score > 0:
            scores[sector] = min(score / 3.0, 1.0)  # 归一化到 0-1
    return sorted(scores.items(), key=lambda x: -x[1])


def scan_diff(yaml_data: dict, ths_map: dict[str, str]) -> dict[str, list[dict]]:
    """扫描全部差异：新增 / 删除 / 更名。
    
    Returns: {"new": [...], "deleted": [...], "renamed": [...]}
    """
    yaml_codes = _all_yaml_codes(yaml_data)
    canonical = yaml_data.get("canonical_sectors") or {}

    new_concepts: list[dict] = []
    deleted_concepts: list[dict] = []
    renamed_concepts: list[dict] = []

    # ── 1. 新增：THS 有但 YAML 无 ──
    for code, name in ths_map.items():
        if code not in yaml_codes:
            suggestions = _classify_new_concept(name)
            top = suggestions[0] if suggestions else ("未匹配", 0.0)
            new_concepts.append({
                "code": code,
                "name": name,
                "suggested_sector": top[0],
                "confidence": round(top[1], 2),
                "auto_assign": top[1] >= 0.8,
            })

    # ── 2. 删除 + 更名：按赛道遍历 YAML ──
    for sector, cfg in canonical.items():
        for cc in (cfg.get("child_concepts") or []):
            ccode = str(cc.get("code", ""))
            cname = str(cc.get("name", ""))
            if not ccode:
                continue
            if ccode not in ths_map:
                # THS 已下线
                deleted_concepts.append({
                    "sector": sector,
                    "code": ccode,
                    "old_name": cname,
                })
            elif ths_map[ccode] != cname:
                # 名称变更
                renamed_concepts.append({
                    "sector": sector,
                    "code": ccode,
                    "old_name": cname,
                    "new_name": ths_map[ccode],
                })

    return {
        "new": new_concepts,
        "deleted": deleted_concepts,
        "renamed": renamed_concepts,
    }


# ══════════════════════════════════════════════════════════════
# Phase 3: 变更应用
# ══════════════════════════════════════════════════════════════

def _apply_renames(yaml_data: dict, renamed: list[dict]) -> int:
    """更新 YAML 中更名的概念名称。"""
    canonical = yaml_data.setdefault("canonical_sectors", {})
    count = 0
    for d in renamed:
        sec_cfg = canonical.get(d["sector"])
        if not sec_cfg:
            continue
        for cc in (sec_cfg.get("child_concepts") or []):
            if str(cc.get("code")) == d["code"]:
                cc["name"] = d["new_name"]
                count += 1
                break
    return count


def _apply_removes(yaml_data: dict, deleted: list[dict]) -> int:
    """从 YAML 中移除已下线概念。"""
    canonical = yaml_data.setdefault("canonical_sectors", {})
    count = 0
    deleted_codes = {d["code"] for d in deleted}
    for sec_cfg in canonical.values():
        sec_cfg["child_concepts"] = [
            cc for cc in sec_cfg.get("child_concepts") or []
            if str(cc.get("code")) not in deleted_codes
        ]
        count += 1
    return count


def _apply_new_auto(yaml_data: dict, new_concepts: list[dict]) -> int:
    """将高置信度(≥80%)新概念自动加入对应赛道。"""
    canonical = yaml_data.setdefault("canonical_sectors", {})
    count = 0
    for nc in new_concepts:
        if not nc["auto_assign"]:
            continue
        sec = nc["suggested_sector"]
        if sec in canonical:
            children = canonical[sec].setdefault("child_concepts", [])
            existing_codes = {str(c.get("code", "")) for c in children}
            if nc["code"] not in existing_codes:
                children.append({"code": nc["code"], "name": nc["name"]})
                count += 1
    return count


# ══════════════════════════════════════════════════════════════
# Phase 4: DB 标签清理
# ══════════════════════════════════════════════════════════════

def _get_db_url() -> str:
    import os
    raw = os.environ.get("COPILOT_DB_URL", "").replace("asyncpg", "psycopg2")
    return raw


def _cleanup_deleted_concept_tags(deleted: list[dict]) -> dict[str, int]:
    """从 S0_doc 记录的 selected_concepts 中移除已下线概念的标签。"""
    if not deleted:
        return {"deleted_concepts": len(deleted), "docs_updated": 0}

    try:
        from sqlalchemy import create_engine, text as sa_text
        engine = create_engine(_get_db_url(), future=True)
    except Exception as e:
        print(f"  [WARN] DB 清理跳过: {e}", file=sys.stderr)
        return {"deleted_concepts": len(deleted), "docs_updated": 0}

    updated = 0
    try:
        with engine.begin() as conn:
            rows = conn.execute(sa_text(
                "SELECT id, scope, snapshot FROM deepsea_indicator_state WHERE scope LIKE 'S0_doc%%'"
            )).fetchall()

            for row in rows:
                snap = row[1]
                if isinstance(snap, str):
                    snap = json.loads(snap)
                if not isinstance(snap, dict):
                    continue

                sel = snap.get("selected_concepts") or []
                if not isinstance(sel, list):
                    continue

                deleted_names = {d["old_name"] for d in deleted}
                cleaned = [s for s in sel if str(s) not in deleted_names]

                if len(cleaned) != len(sel):
                    snap["selected_concepts"] = cleaned
                    conn.execute(
                        sa_text("UPDATE deepsea_indicator_state SET snapshot = :snap WHERE id = :id"),
                        {"snap": json.dumps(snap), "id": row[0]},
                    )
                    updated += 1
    except Exception as e:
        print(f"  [WARN] DB 清理异常: {e}", file=sys.stderr)
    finally:
        engine.dispose()

    return {"deleted_concepts": len(deleted), "docs_updated": updated}


def _cleanup_renamed_concept_tags(renamed: list[dict]) -> dict[str, int]:
    """更新 S0_doc 中已更名概念的标签名。"""
    if not renamed:
        return {"renamed_concepts": len(renamed), "docs_updated": 0}

    try:
        from sqlalchemy import create_engine, text as sa_text
        engine = create_engine(_get_db_url(), future=True)
    except Exception as e:
        print(f"  [WARN] DB 改名跳过: {e}", file=sys.stderr)
        return {"renamed_concepts": len(renamed), "docs_updated": 0}

    rename_map = {d["old_name"]: d["new_name"] for d in renamed}
    updated = 0

    try:
        with engine.begin() as conn:
            rows = conn.execute(sa_text(
                "SELECT id, scope, snapshot FROM deepsea_indicator_state WHERE scope LIKE 'S0_doc%%'"
            )).fetchall()

            for row in rows:
                snap = row[1]
                if isinstance(snap, str):
                    snap = json.loads(snap)
                if not isinstance(snap, dict):
                    continue

                sel = snap.get("selected_concepts") or []
                if not isinstance(sel, list):
                    continue

                changed = False
                new_sel = []
                for s in sel:
                    s_str = str(s)
                    if s_str in rename_map:
                        new_sel.append(rename_map[s_str])
                        changed = True
                    else:
                        new_sel.append(s_str)

                if changed:
                    snap["selected_concepts"] = new_sel
                    conn.execute(
                        sa_text("UPDATE deepsea_indicator_state SET snapshot = :snap WHERE id = :id"),
                        {"snap": json.dumps(snap), "id": row[0]},
                    )
                    updated += 1
    except Exception as e:
        print(f"  [WARN] DB 改名异常: {e}", file=sys.stderr)
    finally:
        engine.dispose()

    return {"renamed_concepts": len(renamed), "docs_updated": updated}


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

def _print_report(diff, header=""):
    """打印差异报告。"""
    new = diff.get("new", [])
    deleted = diff.get("deleted", [])
    renamed = diff.get("renamed", [])

    total = len(new) + len(deleted) + len(renamed)
    if total == 0:
        print(f"\n{header} ✅ 无差异，YAML 与同花顺完全一致。")
        return

    print(f"\n{'='*70}")
    print(f"{header} 发现 {total} 处差异 (新增{len(new)} | 删除{len(deleted)} | 更名{len(renamed)})")
    print(f"{'='*70}")

    if new:
        auto = [n for n in new if n["auto_assign"]]
        manual = [n for n in new if not n["auto_assign"]]
        if auto:
            print(f"\n🟢 将自动归入 ({len(auto)} 个)：")
            for n in auto[:10]:
                print(f"  {n['code']} {n['name']:<20} → {n['suggested_sector']} (置信度 {n['confidence']:.0%})")
        if manual:
            print(f"\n🟡 需人工判定 ({len(manual)} 个)：")
            for n in manual[:10]:
                best = n["suggested_sector"] if n["confidence"] > 0 else "无匹配"
                print(f"  {n['code']} {n['name']:<20} → {best} (置信度 {n['confidence']:.0%})")

    if deleted:
        print(f"\n🔴 已下线 ({len(deleted)} 个 · 将从 YAML 移除 + 清理 DB 标签)：")
        for d in deleted[:10]:
            print(f"  [{d['sector']}] {d['code']} {d['old_name']}")

    if renamed:
        print(f"\n🔄 自动更名 ({len(renamed)} 个)：")
        for d in renamed[:10]:
            print(f"  [{d['sector']}] {d['code']} 「{d['old_name']}」→「{d['new_name']}」")


async def async_main(*, apply: bool = False, retag: bool = False):
    """主入口。"""
    # 1. 加载 YAML
    if not _KEYWORDS_PATH.exists():
        print(f"[ERROR] 文件不存在: {_KEYWORDS_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(_KEYWORDS_PATH, "r", encoding="utf-8") as f:
        yaml_data = yaml.safe_load(f)

    cfg = yaml_data.get("concept_sync") or {}
    if not cfg.get("enabled"):
        print("[INFO] concept_sync.enabled=false，跳过。")
        return

    # 2. 拉取 THS
    print("[INFO] 拉取同花顺概念...")
    ths_map = fetch_ths_concepts()
    if not ths_map:
        print("[ERROR] 无概念数据", file=sys.stderr)
        sys.exit(1)
    print(f"[INFO] 同花顺 {len(ths_map)} 个概念 · YAML {len(_all_yaml_codes(yaml_data))} 个概念")

    # 3. 差异扫描
    diff = scan_diff(yaml_data, ths_map)
    _print_report(diff, "概念同步报告")

    # 4. 应用变更
    if apply:
        yaml_changes = 0

        if diff["renamed"]:
            n = _apply_renames(yaml_data, diff["renamed"])
            yaml_changes += n
            print(f"\n[APPLY] YAML 更名 {n} 项")

            db_result = _cleanup_renamed_concept_tags(diff["renamed"])
            print(f"[APPLY] DB 标签更名 {db_result['docs_updated']} 篇文档")

        if diff["deleted"]:
            n = _apply_removes(yaml_data, diff["deleted"])
            yaml_changes += n
            print(f"\n[APPLY] YAML 移除 {len(diff['deleted'])} 个已下线概念")

            db_result = _cleanup_deleted_concept_tags(diff["deleted"])
            print(f"[APPLY] DB 清理标签 {db_result['docs_updated']} 篇文档")

        if diff["new"]:
            n = _apply_new_auto(yaml_data, diff["new"])
            yaml_changes += n
            print(f"\n[APPLY] YAML 自动新增 {n} 个概念")

            manual = [n for n in diff["new"] if not n["auto_assign"]]
            if manual:
                print(f"[INFO] 剩余 {len(manual)} 个概念需人工判定，见上方报告")

        # 写回 YAML
        if yaml_changes > 0:
            yaml_data.setdefault("concept_sync", {})["last_synced_at"] = datetime.now(timezone.utc).isoformat()
            with open(_KEYWORDS_PATH, "w", encoding="utf-8") as f:
                yaml.safe_dump(yaml_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            print(f"\n✅ 已写入 {_KEYWORDS_PATH}")
        else:
            print("\n[INFO] 无 YAML 变更")

    if retag:
        # TODO: 触发 T1 全量重评分（对新增概念）
        print("\n[TODO] retag 功能待实现：触发 T1 dispatcher 全量重跑")

    print(f"\n[DONE] {datetime.now().isoformat()}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="同花顺概念板块同步 v5.1")
    parser.add_argument("--apply", action="store_true", help="自动写入 YAML + 清理 DB 标签")
    parser.add_argument("--retag", action="store_true", help="(TODO) 触发 T1 重评分对新增概念打标签")
    args = parser.parse_args()
    asyncio.run(async_main(apply=args.apply, retag=args.retag))


if __name__ == "__main__":
    main()
