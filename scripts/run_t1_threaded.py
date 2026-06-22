"""独立 T1 处理——线程池 + 每线程独立事件循环。"""
import sys, time, os, asyncio, json
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, "/app")

from sqlalchemy import create_engine

from apps.copilot.services.deepsea.policy_t1_dispatcher import (
    _fetch_pending_docs, _aggregate_with_decay, _insert_policy_indicator_state,
    _deduplicate_b1_sectors, upsert_policy_indicator_state,
    S0_SCOPE, POLICY_PROBE_KEY,
)
from apps.copilot.services.deepsea.policy_t1_evidence_checker import batch_check_evidence
from apps.copilot.services.deepsea.policy_t1_llm_scorer import score_policy_document

def _score_in_thread(doc):
    """每线程独立 asyncio 事件循环调用 LLM。"""
    return asyncio.run(score_policy_document(doc, model="deepseek-chat"))

def main():
    raw = os.environ.get("COPILOT_DB_URL", "").replace("asyncpg", "psycopg2")
    engine = create_engine(raw, future=True)
    t0 = time.time()

    with engine.begin() as conn:
        pending = _fetch_pending_docs(conn, limit=300, lookback_days=730)

    if not pending:
        print("无待处理文档")
        engine.dispose()
        return

    total = len(pending)
    print(f"待处理 {total} 篇，开始 LLM 评分（5 线程并发）...")

    successes = []
    errors_list = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_score_in_thread, doc): doc["doc_id"] for doc in pending}
        done_count = 0
        for f in as_completed(futures):
            doc_id = futures[f]
            try:
                result = f.result()
                successes.append(result)
                done_count += 1
                if done_count % 20 == 0 or done_count == total:
                    print(f"  T1 进度: {done_count}/{total} ({done_count*100//total}%)")
            except Exception as exc:
                errors_list.append({"doc_id": doc_id, "error": str(exc)[:200]})
                print(f"  T1 失败 {doc_id[:12]}: {exc}")

    elapsed_b1 = time.time() - t0
    print(f"B1 完成: {len(successes)}/{total} 成功, {len(errors_list)} 失败 ({elapsed_b1:.0f}s)")

    if not successes:
        print("B1 全失败")
        engine.dispose()
        return

    # Phase C: evidence check + dedup
    doc_map = {d["doc_id"]: d for d in pending}
    c_successes = []
    for b1 in successes:
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
            print(f"S0聚合: {len(top_sectors)} 赛道")
            for ts in top_sectors[:5]:
                print(f"  {ts['sector']}: comp={ts['composite_score']:.1f} docs={ts['doc_count']} imp={ts.get('imp_force_label','?')}")

    engine.dispose()
    elapsed = time.time() - t0
    print(f"DONE {elapsed:.0f}s")

if __name__ == "__main__":
    main()
