"""独立 T1 处理脚本——避免与 FastAPI 事件循环冲突。"""
import sys, asyncio, json, time, os
sys.path.insert(0, "/app")

from sqlalchemy import create_engine, text

from apps.copilot.services.deepsea.policy_t1_llm_scorer import dispatch_b1
from apps.copilot.services.deepsea.policy_t1_dispatcher import (
    _fetch_pending_docs, _aggregate_with_decay, _insert_policy_indicator_state,
    _deduplicate_b1_sectors, upsert_policy_indicator_state,
    S0_SCOPE, T1_SOURCE, POLICY_PROBE_KEY,
)
from apps.copilot.services.deepsea.policy_t1_evidence_checker import batch_check_evidence

raw = os.environ.get("COPILOT_DB_URL", "").replace("asyncpg", "psycopg2")
engine = create_engine(raw, future=True)

t0 = time.time()

# Phase A: fetch pending
with engine.begin() as conn:
    pending = _fetch_pending_docs(conn, limit=300, lookback_days=730)

if not pending:
    print("无待处理文档")
    engine.dispose()
    sys.exit(0)

total_pending = len(pending)
print(f"待处理 {total_pending} 篇，开始 LLM 评分（5 并发）...")

# Phase B1: LLM scoring
b1_successes, b1_errors = asyncio.run(dispatch_b1(pending))
print(f"B1 完成: {len(b1_successes)}/{total_pending} 成功, {len(b1_errors)} 失败")

if not b1_successes:
    print("B1 全失败")
    engine.dispose()
    sys.exit(1)

# Phase C: evidence check + dedup
doc_map = {d["doc_id"]: d for d in pending}
c_successes = []
for b1 in b1_successes:
    did = b1.get("doc_id", "")
    doc = doc_map.get(did, {})
    ft = str(doc.get("full_text") or "")
    checked_sectors, _ = batch_check_evidence(b1.get("sectors") or [], ft)
    deduped = _deduplicate_b1_sectors(checked_sectors)
    c_successes.append({**b1, "sectors": deduped})

# Write DB
processed = 0
doc_snapshots = []
with engine.begin() as conn:
    for sig in c_successes:
        inserted = _insert_policy_indicator_state(conn, doc_id=sig.get("doc_id", ""), signal=sig)
        if inserted and sig.get("sectors"):
            doc_snapshots.append(sig)
            processed += 1
print(f"DB写入: {processed} 篇")

# Phase B2: aggregate
if doc_snapshots:
    top_sectors, evidence = _aggregate_with_decay(doc_snapshots, pending, top_n=15)
    if top_sectors:
        upsert_policy_indicator_state(top_sectors=top_sectors, evidence=evidence, scope=S0_SCOPE)
        print(f"S0聚合写入: {len(top_sectors)} 赛道")
        for ts in top_sectors[:5]:
            print(f"  {ts['sector']}: composite={ts['composite_score']:.1f} docs={ts['doc_count']} imp={ts.get('imp_force_label','?')}")

engine.dispose()
elapsed = time.time() - t0
print(f"DONE {elapsed:.0f}s")
