"""D5 super_evo step04 CLI — LoRA 训练流水线。

用法:
  python scripts/evo_step04_run.py prep             # 检查训练前置条件
  python scripts/evo_step04_run.py sanity-train     # dry-run sanity 训练（--max-steps 50，不需 GPU）
  python scripts/evo_step04_run.py train <dim>      # 真实训练（需 GPU）
  python scripts/evo_step04_run.py status           # lora_versions 注册表快照
  python scripts/evo_step04_run.py list-configs     # 列出可用 yaml 配置

# DECISION_PENDING: 真实 GPU 训练（train 子命令）需 GPU ≥24GB（或 QLoRA ≥16GB）
# 当前 dry_run=True 的 sanity-train 不需 GPU，用于验证流水线正确性。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_04_C3_LLaMA_Factory训练流水线.md §7.2]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

CONFIGS_DIR = (
    Path(__file__).parent.parent
    / "apps"
    / "super_evo"
    / "training"
    / "configs"
)

DIM_MAP = {
    "cryo": "lora_cryo.yaml",
    "thrust": "lora_thrust.yaml",
    "narrative": "lora_narrative.yaml",
}


def _load_dim_config(dim: str) -> dict:
    import yaml

    fname = DIM_MAP.get(dim)
    if not fname:
        raise ValueError(f"未知 dim: {dim}，可选 {list(DIM_MAP.keys())}")
    p = CONFIGS_DIR / fname
    if not p.exists():
        raise FileNotFoundError(f"缺配置文件: {p}")
    with p.open() as f:
        return yaml.safe_load(f)


def _run_prep() -> None:
    """检查前置条件：模板 YAML + 3 维 config + llamafactory（optional）。"""
    from apps.super_evo.training.gpu_check import check_gpu, is_llamafactory_installed

    issues = 0

    # 1. 配置文件
    for dim, fname in DIM_MAP.items():
        p = CONFIGS_DIR / fname
        if p.exists():
            print(f"  lora_{dim}.yaml ✅")
        else:
            print(f"  lora_{dim}.yaml ❌ 缺失")
            issues += 1

    template = CONFIGS_DIR / "_template_lora.yaml"
    if template.exists():
        print(f"  _template_lora.yaml ✅")
    else:
        print(f"  _template_lora.yaml ❌")
        issues += 1

    # 2. llamafactory-cli（sanity 不需要，真训练需要）
    if is_llamafactory_installed():
        print("  llamafactory-cli ✅")
    else:
        print("  llamafactory-cli ⚠️  未安装（sanity dry-run 不需要；真训练需要）")

    # 3. GPU
    gpu = check_gpu(min_free_mib=18_000)
    if gpu.available:
        print(f"  GPU: {gpu.names} free={gpu.free_mib}MiB ✅")
    else:
        print(
            f"  GPU: 不可用（{gpu.reason}）"
            f"  → DECISION_PENDING: 真实训练需 GPU；sanity dry-run 可继续"
        )

    print(f"\n▶ prep 检查完成: {'全通过 ✅' if issues == 0 else f'{issues} 项问题 ⚠️'}")
    sys.exit(0 if issues == 0 else 1)


def _run_sanity_train() -> None:
    """dry-run sanity 训练（--max-steps 50）——不需 GPU，验证流水线正确性。"""
    import tempfile

    from apps.super_evo.training.data_prep import split_verified_jsonl
    from apps.super_evo.training.trainer import TrainRequest, run_training

    print("▶ [evo-step04-sanity-train] dry-run sanity（max_steps=50，不需 GPU）")

    # 生成最小 sanity 数据集（require_verified=False，沙箱专用）
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        jsonl = tmp / "sanity.jsonl"
        # 写 20 条 dummy verified 样本
        recs = []
        for i in range(20):
            recs.append(
                json.dumps(
                    {
                        "instruction": f"请分析样本{i}",
                        "input": "",
                        "output": json.dumps({"decision": "pass", "risk_score": 0.1}),
                        "metadata": {
                            "verified": True,
                            "task_type": "financial_fraud",
                            "sample_id": f"sanity_{i}",
                        },
                    },
                    ensure_ascii=False,
                )
            )
        jsonl.write_text("\n".join(recs), encoding="utf-8")

        split_result = split_verified_jsonl(
            jsonl, tmp / "llama_factory", "financial_fraud"
        )
        print(
            f"  sanity 数据: train={split_result.n_train} val={split_result.n_val} test={split_result.n_test}"
        )

        req = TrainRequest(
            lora_name="sanity_v0",
            task="financial_fraud",
            base_model="models/Qwen2.5-7B-Instruct",
            rank=16,
            epochs=1,
            max_steps=50,
            dataset_dir=str(tmp / "llama_factory"),
            output_root=str(tmp / "output"),
        )
        result = run_training(req, dry_run=True)

    if result.return_code == 0:
        print(f"  sanity train ✅ adapter_path={result.adapter_path}")
        print(f"  train_loss={result.final_train_loss} eval_loss={result.final_eval_loss}")
    else:
        print(f"  sanity train ❌ return_code={result.return_code}")
        print(f"  日志尾: {result.stdout_tail[-200:]}")
        sys.exit(1)

    print("\n▶ 做了什么: dry-run 验证 trainer.py + data_prep + config 渲染流水线")
    print("▶ 期望什么: return_code=0，adapter_path 存在（dry-run 占位文件）")
    print("▶ 实际什么: ✅ 流水线验证通过（无 GPU，dry_run=True）")
    print()
    print("# DECISION_PENDING: GPU 真实训练")
    print(
        "#   当前为 dry_run 模式（llamafactory-cli 未调用）。"
        "真实训练需 GPU ≥24GB（或 QLoRA ≥16GB）。"
    )
    print("#   请确认后执行: python scripts/evo_step04_run.py train <dim>")


def _run_train(dim: str) -> None:
    """真实训练（需要 GPU + llamafactory-cli）。"""
    from apps.super_evo.training.gpu_check import check_gpu, is_llamafactory_installed
    from apps.super_evo.training.trainer import TrainRequest, run_training

    # 硬前置检查
    if not is_llamafactory_installed():
        print("❌ llamafactory-cli 未安装。请先安装: pip install llamafactory")
        print("# DECISION_PENDING: GPU 环境准备")
        sys.exit(1)

    gpu = check_gpu(min_free_mib=16_000)
    if not gpu.available:
        print(f"❌ GPU 不可用: {gpu.reason}")
        print("# DECISION_PENDING: 需 GPU ≥16GB（QLoRA）或 ≥24GB（fp16 LoRA）")
        print("#   建议：阿里云 ecs.gn6i-c4g1.xlarge（V100-16G，~¥5/h）")
        sys.exit(1)

    cfg = _load_dim_config(dim)
    req = TrainRequest(
        lora_name=cfg.get("lora_name", f"{dim}_lora_v1"),
        task=cfg.get("task", "financial_fraud"),
        rank=cfg.get("rank", 16),
        epochs=cfg.get("epochs", 3),
        learning_rate=cfg.get("learning_rate", 2e-4),
    )
    print(f"▶ 开始训练 dim={dim} lora_name={req.lora_name} rank={req.rank}")
    result = run_training(req, dry_run=False)

    if result.return_code == 0:
        print(f"  训练完成 ✅ adapter={result.adapter_path}")
        print(f"  train_loss={result.final_train_loss}")
    else:
        print(f"  训练失败 ❌ return_code={result.return_code}")
        sys.exit(1)


def _run_status() -> None:
    """查 lora_versions 注册表（DB 已初始化时）。"""
    from sqlalchemy import create_engine, text

    from apps.super_evo.config import settings

    db_url = settings.db_url
    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT lora_name, version, status, is_dry_run, created_at "
                    "FROM lora_versions ORDER BY created_at DESC LIMIT 20"
                )
            ).fetchall()
        if rows:
            print(f"lora_versions 注册表（最近 {len(rows)} 条）:")
            for r in rows:
                dry = "（dry_run）" if r[3] else ""
                print(f"  {r[0]} v{r[1]} status={r[2]} {dry} at={str(r[4])[:10]}")
        else:
            print("lora_versions 为空（尚未训练或 DB 未初始化）")
    except Exception as exc:
        print(f"  ⚠️  lora_versions 查询失败: {exc}（表可能未建，跑 prep 后再查）")


def _run_list_configs() -> None:
    for dim, fname in DIM_MAP.items():
        p = CONFIGS_DIR / fname
        status = "✅" if p.exists() else "❌"
        print(f"  {dim}: {fname} {status}")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "prep":
        _run_prep()
    elif cmd == "sanity-train":
        _run_sanity_train()
    elif cmd == "train":
        dim = sys.argv[2] if len(sys.argv) > 2 else "cryo"
        _run_train(dim)
    elif cmd == "status":
        _run_status()
    elif cmd == "list-configs":
        _run_list_configs()
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
