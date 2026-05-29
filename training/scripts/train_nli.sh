#!/bin/bash
# train_nli.sh — narrative_nli_lora_v1 训练脚本（可重复执行）
# [Ref: 03_/03_维度三/.../step_05_叙事一致性NLI_LoRA.md §C]
# BLOCKED: 无 GPU ≥16GB 时此脚本不可执行；tier-2 请用 P-step_04 diting-training chart

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "▶ [watch-step05-train] narrative_nli_lora_v1 LoRA 训练"
echo "  做了什么：使用 LLaMA-Factory 训练 Qwen2.5-7B NLI 分类器"
echo "  期望：outputs/narrative_nli_lora_v1/ 目录下包含 adapter_model.bin"
echo "  实际：见训练日志"

# 先检查 LLaMA-Factory 是否可用
if ! python3 -c "import llamafactory" 2>/dev/null; then
    echo "❌ LLaMA-Factory 未安装，请先运行: pip install llamafactory"
    echo "BLOCKED(llamafactory_not_installed)"
    exit 1
fi

# 检查 GPU
if ! python3 -c "import torch; assert torch.cuda.is_available(), 'no CUDA'" 2>/dev/null; then
    echo "❌ 无 CUDA GPU；tier-1 可跑 sanity（1 step），tier-2 需 P-step_04 diting-training"
    echo "BLOCKED(gpu_unavailable)"
    exit 1
fi

cd "$REPO_ROOT"
llamafactory-cli train training/configs/narrative_nli_lora.yaml

echo "✅ 训练完成：outputs/narrative_nli_lora_v1/"
