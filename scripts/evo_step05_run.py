"""D5 super_evo step05 CLI — Holdout 评测 + CI Block 验证。

用法：
  python scripts/evo_step05_run.py prep
  python scripts/evo_step05_run.py generate-holdout
  python scripts/evo_step05_run.py evaluate <dim> [--lora-version-id N] [--mode mock|vllm]
  python scripts/evo_step05_run.py regression-sim <dim>    # 模拟退化 → blocked=True
  python scripts/evo_step05_run.py leak-check <dim>
  python scripts/evo_step05_run.py status

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_05_Holdout评测器与CI_Block.md §7.2]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HOLDOUT_ROOT = Path("training/data/holdout")
DIMS = ["cryo", "thrust", "narrative"]


# ---------------------------------------------------------------------------
# prep — 前置条件检查
# ---------------------------------------------------------------------------


def cmd_prep() -> int:
    """检查 Holdout 文件、vLLM（可选）、GPU（可选）。"""
    print("▶ [evo-step05-prep] 检查前置条件")
    ok = True

    for dim in DIMS:
        path = HOLDOUT_ROOT / dim / "holdout.jsonl"
        if path.exists():
            n = sum(1 for _ in path.open(encoding="utf-8") if _.strip())
            print(f"  holdout/{dim}/holdout.jsonl ✅ ({n} 条)")
        else:
            print(f"  holdout/{dim}/holdout.jsonl ❌ 缺失（运行 generate-holdout 生成）")
            ok = False

    # vLLM（可选，非硬阻塞）
    vllm_url = Path(".env").read_text(encoding="utf-8") if Path(".env").exists() else ""
    if "VLLM_URL" in vllm_url:
        print("  VLLM_URL ✅（env）")
    else:
        print("  VLLM_URL ⚠️  未设置（mock 模式可用；真实评测 DECISION_PENDING）")

    # GPU（可选）
    try:
        import torch
        if torch.cuda.is_available():
            print(f"  GPU ✅ {torch.cuda.get_device_name(0)}")
        else:
            print("  GPU ⚠️  不可用（mock 模式可用；真实 vLLM 推理 DECISION_PENDING）")
    except ImportError:
        print("  GPU ⚠️  torch 未安装（mock 模式可用；真实推理 DECISION_PENDING）")

    if ok:
        print("▶ prep 完成 ✅")
        return 0
    else:
        print("▶ prep 失败：缺少 holdout 数据（先运行 generate-holdout）")
        return 1


# ---------------------------------------------------------------------------
# generate-holdout — 创建锁库数据（扩标注）
# ---------------------------------------------------------------------------


def cmd_generate_holdout() -> int:
    """生成 D1=50、D2/D3=30 的 holdout 数据（永久锁库）。"""
    print("▶ [evo-step05-generate-holdout] 生成 Holdout 锁库数据")
    from scripts.generate_holdout_data import generate_holdout, write_holdout

    specs = {"cryo": 50, "thrust": 30, "narrative": 30}
    for dim, n in specs.items():
        cases = generate_holdout(dim, n)
        out = write_holdout(dim, cases, HOLDOUT_ROOT)
        print(f"  {dim}: {n} 条 → {out} ✅")
    print("▶ holdout 锁库完成（禁止将此目录用于训练集）")
    return 0


# ---------------------------------------------------------------------------
# evaluate — 执行 Holdout 评测
# ---------------------------------------------------------------------------


def cmd_evaluate(dim: str, lora_version_id: int = 0, mode: str = "mock") -> int:
    """评测指定维度的 Holdout。"""
    from apps.super_evo.quality.holdout_evaluator import HoldoutEvaluator

    if dim not in DIMS:
        print(f"❌ 维度 {dim!r} 不合法，可选：{DIMS}")
        return 1

    print(f"▶ [evo-step05-evaluate-{dim}] mode={mode} lora_version_id={lora_version_id}")

    vllm_url = os.environ.get("VLLM_URL")
    adapter_path = f"lora-{dim}" if mode == "vllm" else None

    evaluator = HoldoutEvaluator(
        dim=dim,
        lora_version_id=lora_version_id,
        holdout_root=HOLDOUT_ROOT,
        vllm_url=vllm_url,
        mode=mode,
    )

    try:
        report = evaluator.evaluate(adapter_path=adapter_path)
    except FileNotFoundError as e:
        print(f"  ❌ {e}")
        print("  → 请先运行 make evo-step05-generate-holdout")
        return 1

    print(f"  n_cases={report.n_cases}")
    print(f"  recall={report.metrics.recall:.4f}  precision={report.metrics.precision:.4f}  f1={report.metrics.f1:.4f}")
    print(f"  is_first_run={report.is_first_run}  blocked={report.blocked}  mode={report.inference_mode}")
    if report.block_reason:
        print(f"  block_reason: {report.block_reason}")

    if report.blocked:
        print("  ⚠️  BLOCKED（触发 CI Block）")
        return 1 if not report.is_first_run else 0
    print("  ✅ PASS")
    return 0


# ---------------------------------------------------------------------------
# regression-sim — 模拟退化 → 触发 blocked=True
# ---------------------------------------------------------------------------


def cmd_regression_sim(dim: str) -> int:
    """模拟一次 5% 以上退化，验证 Block 逻辑工作（CI 验证用）。

    [Ref: step_05 §7.2 evo-step05-regression-sim]
    """
    from apps.super_evo.quality.regression_gate import apply_regression_gate

    print(f"▶ [evo-step05-regression-sim] dim={dim} 模拟退化")

    gate = apply_regression_gate(
        current_recall=0.80,
        current_precision=0.82,
        current_f1=0.81,
        baseline_recall=0.90,   # 退化 11.1%
        baseline_precision=0.88,
        baseline_f1=0.89,
        dim=dim,
    )

    print(f"  delta_recall={gate.delta_recall:.4f}  delta_f1={gate.delta_f1:.4f}")
    print(f"  blocked={gate.blocked}")
    if gate.blocked:
        print(f"  block_reason: {gate.block_reason}")
        print("  ✅ CI Block 模拟成功（blocked=True，exit 1）")
        return 1  # 模拟 CI exit 1
    print("  ❌ 未触发 Block（测试失败）")
    return 1


# ---------------------------------------------------------------------------
# leak-check — 验证 holdout 与训练集无重叠
# ---------------------------------------------------------------------------


def cmd_leak_check(dim: str) -> int:
    """检查 holdout 与 verified 训练集的 sample_id 无重叠（G：leak check 0 命中）。"""
    print(f"▶ [evo-step05-leak-check] dim={dim}")

    holdout_path = HOLDOUT_ROOT / dim / "holdout.jsonl"
    if not holdout_path.exists():
        print(f"  ❌ holdout/{dim}/holdout.jsonl 不存在")
        return 1

    holdout_ids = set()
    with holdout_path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                sid = rec.get("metadata", {}).get("sample_id", "")
                if sid:
                    holdout_ids.add(sid)

    # 扫描训练数据目录中的 verified jsonl
    train_dir = Path("training/data/distilled")
    train_ids = set()
    scanned = 0
    for jsonl_path in train_dir.rglob("*.jsonl"):
        if "holdout" in str(jsonl_path):
            continue
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        rec = json.loads(line)
                        sid = rec.get("metadata", {}).get("sample_id", "")
                        if sid:
                            train_ids.add(sid)
                        scanned += 1
                    except json.JSONDecodeError:
                        pass

    overlap = holdout_ids & train_ids
    print(f"  holdout ids: {len(holdout_ids)}，训练集 ids（扫描{scanned}行）: {len(train_ids)}")
    if overlap:
        print(f"  ❌ 发现重叠 {len(overlap)} 条：{list(overlap)[:5]}...")
        return 1
    print(f"  ✅ leak check 通过：0 命中重叠（H2）")
    return 0


# ---------------------------------------------------------------------------
# status — 显示最近评测记录
# ---------------------------------------------------------------------------


def cmd_status() -> int:
    """显示 holdout 数据统计（DB 持久化版本待接 DB）。"""
    print("▶ [evo-step05-status] Holdout 数据状态")
    for dim in DIMS:
        path = HOLDOUT_ROOT / dim / "holdout.jsonl"
        if path.exists():
            n = sum(1 for _ in path.open(encoding="utf-8") if _.strip())
            req_min = 50 if dim == "cryo" else 30
            status = "✅" if n >= req_min else "⚠️"
            print(f"  {status} {dim}: {n} 条（要求≥{req_min}）")
        else:
            print(f"  ❌ {dim}: 缺失")
    print("  DB 评测记录：待接 holdout_evaluations 表（step_05 tier-2）")
    return 0


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 0

    cmd = args[0]
    if cmd == "prep":
        return cmd_prep()
    elif cmd == "generate-holdout":
        return cmd_generate_holdout()
    elif cmd == "evaluate":
        dim = args[1] if len(args) > 1 else "cryo"
        lora_id = int(args[2]) if len(args) > 2 else 0
        mode = args[3] if len(args) > 3 else "mock"
        return cmd_evaluate(dim, lora_id, mode)
    elif cmd == "regression-sim":
        dim = args[1] if len(args) > 1 else "cryo"
        return cmd_regression_sim(dim)
    elif cmd == "leak-check":
        dim = args[1] if len(args) > 1 else "cryo"
        return cmd_leak_check(dim)
    elif cmd == "status":
        return cmd_status()
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
