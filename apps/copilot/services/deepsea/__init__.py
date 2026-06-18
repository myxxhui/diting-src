"""DeepSea V2.0 语义量化中台 · Copilot 内嵌服务。

长文语义只读 PG 契约 + 对象湖；**禁止** OpenSearch/BM25（29_ §1.3 · §8 废止 doc_retriever）。

[Ref: 29_ §5.4 · 28_ §2.13]
"""
from apps.copilot.services.deepsea.dispatcher import dispatch_cohort_inference, dispatch_doc_inference
from apps.copilot.services.deepsea.policy_reader import (
    POLICY_PROBE_KEY,
    check_deepsea_pg_ready,
    read_policy_sectors_from_pg,
    upsert_policy_indicator_state,
)
from apps.copilot.services.deepsea.policy_t1_dispatcher import dispatch_policy_t1

__all__ = [
    "POLICY_PROBE_KEY",
    "check_deepsea_pg_ready",
    "dispatch_cohort_inference",
    "dispatch_doc_inference",
    "dispatch_policy_t1",
    "read_policy_sectors_from_pg",
    "upsert_policy_indicator_state",
]
