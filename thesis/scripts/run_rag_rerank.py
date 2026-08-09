"""RAG++ — an advanced-RAG baseline: dense retrieval followed by cross-encoder
re-ranking. This is the "stronger retriever" control for the state-of-the-art
positioning in Chapter 5: it tests whether a better ranking of the same corpus —
rather than SupplierMind's per-constraint verification gate — could close the gap to
the agentic system.

WHAT IT DOES, per query:
  1. Dense-retrieve a wide candidate pool from the same Voyage+Milvus index the RAG
     baseline (P2) uses:      vector_store.search(query, top_k=POOL)
  2. Re-rank those candidates with a cross-encoder that scores (query, supplier)
     pairs directly — the standard advanced-RAG technique. Supplier text is read from
     the corpus file, so no database connection is required.
  3. Keep the top 5 and score against SupplierBench-25 ground truth (Precision@5,
     Recall@5, MRR), overall and by difficulty tier.

REQUIREMENTS:
  - The retrieval stack up (Milvus with the 10k corpus ingested), reachable as P2 uses it.
  - Provider keys set:  VOYAGE_API_KEY (query embedding) and OPENAI_API_KEY.
  - The cross-encoder:  uv pip install sentence-transformers
    (if pymilvus complains about pkg_resources, also:  uv pip install "setuptools<80")

RUN (from apps/backend, so the app package and PYTHONPATH resolve):
    cd apps/backend
    PYTHONPATH=. VOYAGE_API_KEY=... OPENAI_API_KEY=... \
        .venv/bin/python ../../thesis/scripts/run_rag_rerank.py --pool 30
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "apps" / "backend" / "data" / "suppliers_synthetic_10k.json"
BENCH = ROOT / "thesis" / "benchmark" / "supplierbench25_10k.json"
OUT = ROOT / "thesis" / "results" / "10k" / "RAG_RERANK.json"
CROSS_ENCODER = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def supplier_text(s: dict) -> str:
    return (f"{s.get('name','')}. Category: {s.get('category','')}. "
            f"Location: {s.get('city','')}, {s.get('country','')}. "
            f"Certifications: {s.get('certifications','')}. "
            f"Capacity: {s.get('capacity_value','')} {s.get('capacity_unit','')}. "
            f"Lead time: {s.get('lead_time_days','')} days. {s.get('description','')}")


def precision_at_k(ret, rel, k=5):
    return sum(1 for r in ret[:k] if r in rel) / k if ret else 0.0


def recall_at_k(ret, rel, k=5):
    return sum(1 for r in ret[:k] if r in rel) / len(rel) if rel else 0.0


def reciprocal_rank(ret, rel, k=5):
    for i, r in enumerate(ret[:k]):
        if r in rel:
            return 1.0 / (i + 1)
    return 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=int, default=30, help="dense candidate pool size")
    args = ap.parse_args()
    if not os.environ.get("VOYAGE_API_KEY"):
        raise SystemExit("Set VOYAGE_API_KEY (and OPENAI_API_KEY) in the environment.")
    os.environ.setdefault("EMBEDDING_PROVIDER", "voyage")

    from app.core.cache import InMemoryCache, set_cache_instance
    from app.core.vector_store import create_vector_store, set_vector_store_instance
    from sentence_transformers import CrossEncoder

    set_cache_instance(InMemoryCache())
    vs = create_vector_store()
    set_vector_store_instance(vs)
    reranker = CrossEncoder(CROSS_ENCODER)
    corpus = {str(s["id"]): s for s in json.loads(CORPUS.read_text())}
    queries = json.loads(BENCH.read_text())

    rows, by_tier = [], {}
    for q in queries:
        rel = set(q["ground_truth_supplier_ids"])
        hits = vs.search(q["raw_query"], top_k=args.pool)
        ids = [str(h.supplier_id) for h in hits]
        if ids:
            pairs = [(q["raw_query"], supplier_text(corpus.get(i, {}))) for i in ids]
            scores = reranker.predict(pairs)
            top5 = [i for _, i in sorted(zip(scores, ids), key=lambda t: t[0], reverse=True)][:5]
        else:
            top5 = []
        p5 = precision_at_k(top5, rel)
        rows.append({"raw_query": q["raw_query"], "difficulty": q["difficulty"],
                     "retrieved_ids": top5, "precision_at_5": p5,
                     "recall_at_5": recall_at_k(top5, rel),
                     "reciprocal_rank": reciprocal_rank(top5, rel), "pool_size": len(ids)})
        by_tier.setdefault(q["difficulty"], []).append(p5)
        print(f"  [{q['difficulty']:6}] pool={len(ids):2} P@5={p5:.2f}  {q['raw_query'][:52]}")

    overall = statistics.mean(r["precision_at_5"] for r in rows)
    tiers = {t: round(statistics.mean(v), 3) for t, v in by_tier.items()}
    OUT.write_text(json.dumps({"system": "rag_rerank", "pool": args.pool,
                               "cross_encoder": CROSS_ENCODER, "precision_at_5": overall,
                               "precision_at_5_by_tier": tiers, "per_query": rows}, indent=2))
    print(f"\nRAG++ Precision@5 = {overall:.3f}   by tier: {tiers}   ->  wrote {OUT.name}")


if __name__ == "__main__":
    main()
