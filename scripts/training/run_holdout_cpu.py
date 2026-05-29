#!/usr/bin/env python3
"""
D5 step_05 tier-2 Holdout 评测 - CPU 推理版本
GPU NoStock 时使用真实模型 + LoRA adapter 在 CPU 上推理（非 mock）

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_05_Holdout评测器与CI_Block.md §7.1-B]
"""
import json
import logging
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_MODEL = "/mnt/titan-data/models/Qwen2.5-1.5B-Instruct"
ADAPTER_ROOT = "/mnt/titan-data/diting-src/output"
HOLDOUT_ROOT = "/mnt/titan-data/diting-src/training/data/holdout"
OUTPUT_FILE = "/mnt/titan-data/diting-src/output/holdout_results_cpu.json"

DIMS = [
    ("cryo", "cryo_lora_v1", 50),
    ("thrust", "thrust_lora_v1", 30),
    ("narrative", "narrative_lora_v1", 30),
]


@dataclass
class InferResult:
    sample_id: str
    prediction: str
    label: str


def load_holdout(dim: str) -> list[dict]:
    path = Path(HOLDOUT_ROOT) / dim / "holdout.jsonl"
    cases = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    logger.info("[%s] 加载 holdout %d 条", dim, len(cases))
    return cases


def extract_label(case: dict) -> str:
    """从 case['output'] 或预测文本提取标签。
    兼容 JSON 格式（{"label":"block"}）和自然语言输出（关键词提取）。
    """
    output = case.get("output", "")
    if isinstance(output, dict):
        return str(output.get("label", output.get("decision", "unknown")))
    if isinstance(output, str):
        # 1) 尝试 JSON 解析
        try:
            d = json.loads(output)
            if "label" in d:
                return str(d["label"])
            if "decision" in d:
                return str(d["decision"])
        except Exception:
            pass
        # 2) 在文本中寻找 JSON 片段
        import re
        m = re.search(r'"(?:label|decision)"\s*:\s*"([^"]+)"', output)
        if m:
            return m.group(1)
        # 3) 关键词兜底（适用于模型输出长文本时）
        text = output.lower()
        # cryo: block / pass
        if "触发极寒" in output or "触发防御" in output or "需要防御" in output:
            return "block"
        if "不触发" in output or "风险可控" in output or "条件未满足" in output:
            return "pass"
        if "block" in text:
            return "block"
        if "pass" in text:
            return "pass"
        # thrust: bull / bear / hold
        if "做多" in output or "看多" in output or "买入" in output or "bull" in text:
            return "bull"
        if "做空" in output or "看空" in output or "卖出" in output or "bear" in text:
            return "bear"
        if "持有" in output or "观望" in output or "hold" in text:
            return "hold"
        # narrative: 直接返回原始文本前30字
        return output.strip()[:30]
    return str(output)


def run_dim_inference(
    dim: str,
    adapter_name: str,
    cases: list[dict],
    tokenizer,
) -> list[InferResult]:
    """每个 dim 独立加载 base + LoRA adapter，推理后释放内存。"""
    import torch
    from transformers import AutoModelForCausalLM
    from peft import PeftModel

    adapter_path = Path(ADAPTER_ROOT) / adapter_name
    if not adapter_path.exists():
        logger.error("[%s] adapter 不存在: %s", dim, adapter_path)
        return []

    logger.info("[%s] 加载基础模型 + LoRA adapter: %s", dim, adapter_path)
    base = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16,
        device_map="cpu",
        trust_remote_code=True,
    )
    lora_model = PeftModel.from_pretrained(base, str(adapter_path))
    lora_model.eval()

    results = []
    for i, case in enumerate(cases):
        # 使用 Chat Template（与 LLaMA Factory 训练格式一致）
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": f"{case.get('instruction', '')}\n{case.get('input', '')}"},
        ]
        try:
            # apply_chat_template 添加 assistant 开头，不自动添加 EOS
            input_text = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        except Exception:
            # fallback: 手动拼接 Qwen 格式
            inst = case.get("instruction", "")
            inp = case.get("input", "")
            input_text = (
                f"<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n"
                f"<|im_start|>user\n{inst}\n{inp}<|im_end|>\n"
                f"<|im_start|>assistant\n"
            )
        inputs = tokenizer(input_text, return_tensors="pt", max_length=1024, truncation=True)
        with torch.no_grad():
            output_ids = lora_model.generate(
                **inputs,
                max_new_tokens=32,  # 输出为短 JSON label，32 token 足够
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        generated = output_ids[0][inputs["input_ids"].shape[1]:]
        raw_text = tokenizer.decode(generated, skip_special_tokens=True).strip()

        label = extract_label(case)
        # 对模型输出也做 label 提取（模型可能输出 JSON 格式 {"label":"block"}）
        pred_label = extract_label({"output": raw_text})

        sid = case.get("metadata", {})
        if isinstance(sid, str):
            try:
                sid = json.loads(sid.replace("'", '"'))
            except Exception:
                sid = {}
        sample_id = sid.get("sample_id", f"{dim}_{i}")

        results.append(InferResult(sample_id=sample_id, prediction=pred_label, label=label))
        if i < 3:  # 前3条打印调试信息
            logger.info("[%s] sample %d: label=%s pred_raw='%s' pred=%s", dim, i, label, raw_text[:80], pred_label)
        if (i + 1) % 5 == 0:
            logger.info("[%s] 进度 %d/%d", dim, i + 1, len(cases))

    logger.info("[%s] 推理完成 %d 条", dim, len(results))
    del lora_model, base
    return results


def compute_metrics(results: list[InferResult]) -> dict:
    if not results:
        return {"recall": 0.0, "precision": 0.0, "f1": 0.0, "n_cases": 0}

    labels = sorted({r.label for r in results})
    per_class = {}
    for label in labels:
        tp = sum(1 for r in results if r.label == label and r.prediction == label)
        fn = sum(1 for r in results if r.label == label and r.prediction != label)
        fp = sum(1 for r in results if r.label != label and r.prediction == label)
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        per_class[label] = {"recall": round(rec, 4), "precision": round(prec, 4), "f1": round(f1, 4),
                            "tp": tp, "fn": fn, "fp": fp}

    macro_recall = sum(v["recall"] for v in per_class.values()) / len(per_class)
    macro_prec = sum(v["precision"] for v in per_class.values()) / len(per_class)
    macro_f1 = sum(v["f1"] for v in per_class.values()) / len(per_class)

    return {
        "recall": round(macro_recall, 4),
        "precision": round(macro_prec, 4),
        "f1": round(macro_f1, 4),
        "n_cases": len(results),
        "per_class": per_class,
    }


def main():
    logger.info("=== D5 step_05 Holdout CPU 推理评测 ===")
    logger.info("基础模型: %s", BASE_MODEL)

    logger.info("加载 tokenizer...")
    try:
        from transformers import AutoTokenizer
    except ImportError as e:
        logger.error("缺少依赖: %s · 请先 pip install torch transformers peft", e)
        sys.exit(1)

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    logger.info("✅ Tokenizer 加载完成")

    all_results = {}

    for dim, adapter_name, expected_n in DIMS:
        logger.info("--- 维度: %s ---", dim)
        try:
            cases = load_holdout(dim)
            results = run_dim_inference(dim, adapter_name, cases, tokenizer)
            metrics = compute_metrics(results)
            all_results[dim] = {
                "metrics": metrics,
                "inference_mode": "cpu_transformers_lora",
                "n_cases": len(results),
                "expected_n": expected_n,
                "samples": [
                    {"id": r.sample_id, "pred": r.prediction[:100], "label": r.label}
                    for r in results[:5]
                ],
            }
            logger.info(
                "[%s] recall=%.4f precision=%.4f f1=%.4f n=%d",
                dim, metrics["recall"], metrics["precision"], metrics["f1"], metrics["n_cases"]
            )
        except Exception as e:
            logger.error("[%s] 评测失败: %s", dim, e, exc_info=True)
            all_results[dim] = {"error": str(e)}

    # 输出结果
    out_path = Path(OUTPUT_FILE)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    logger.info("=== 评测结果 ===")
    for dim, result in all_results.items():
        if "metrics" in result:
            m = result["metrics"]
            logger.info(
                "[%s] recall=%.4f precision=%.4f f1=%.4f (n=%d, mode=%s)",
                dim, m["recall"], m["precision"], m["f1"], m["n_cases"],
                result.get("inference_mode", "?")
            )
        else:
            logger.error("[%s] 失败: %s", dim, result.get("error"))

    logger.info("结果已写入: %s", OUTPUT_FILE)
    logger.info("=== 完成 ===")


if __name__ == "__main__":
    main()
