"""导出 teacher_distill verified=TRUE → LLaMA-Factory JSON."""
from apps.cryo_guard.distillation.exporter import export_engine_to_llama_factory

ENGINES = ("financial_fraud", "shareholder_integrity", "related_party")

for eng in ENGINES:
    s = export_engine_to_llama_factory(eng)
    print(f"  {eng}: {s}")
