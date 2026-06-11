"""DeepSea V2.0 语义量化中台 · Copilot 内嵌服务。

[Ref: 29_ §5.4 · 28_ §2.13]
"""
from apps.copilot.services.deepsea.dispatcher import dispatch_cohort_inference, dispatch_doc_inference

__all__ = ["dispatch_cohort_inference", "dispatch_doc_inference"]
