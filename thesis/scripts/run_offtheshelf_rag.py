"""Off-the-shelf RAG baseline for the state-of-the-art positioning (Chapter 5).

Instead of the study's own minimal RAG (P2), this runs a *standard, widely-used* RAG
framework — LlamaIndex — over the same corpus and the same 25 SupplierBench-25 queries.
Its role is to answer the fair objection that P2 is a weak, self-built baseline: this
one is a community-standard implementation, so if SupplierMind still leads, the result
is not an artefact of a hand-tuned strawman.

It is deliberately self-contained: it needs only an OpenAI key and the corpus file — no
Milvus, no Postgres, no app modules. It builds its own vector index from the corpus,
retrieves the top-5 suppliers per query, and scores them against ground truth with the
same metrics used elsewhere in the study.

SETUP (one-off):
    python -m pip install "llama-index>=0.11"
    export OPENAI_API_KEY=...            # use a FRESH key; never commit it

RUN (from the repository root):
    python thesis/scripts/run_offtheshelf_rag.py
    # options: --top-k 5  --embed-model text-embedding-3-small  --limit N (smoke test)

Cost is a few US cents (embedding 10k short supplier records once).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "apps" / "backend" / "data" / "suppliers_synthetic_10k.json"
BENCH = ROOT / "thesis" / "benchmark" / "supplierbench25_10k.json"
OUT = ROOT / "thesis" / "results" / "10k" / "OFFTHESHELF_RAG.json"


def supplier_document(s: dict) -> str:
    """One document per supplier — the same 'one atomic record' chunking the study uses."""
    return (
        f"{s.get('name','')}. "
        f"Category: {s.get('category','')}. "
        f"Location: {s.get('city','')}, {s.get('country','')}. "
        f"Certifications: {s.get('certifications','')}. "
        f"Capacity: {s.get('capacity_value','')} {s.get('capacity_unit','')}. "
        f"Lead time: {s.get('lead_time_days','')} days. "
        f"{s.get('description','')}"
    )


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
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--embed-model", default="text-embedding-3-small")
    ap.add_argument("--limit", type=int, default=None, help="index only N suppliers (smoke test)")
    args = ap.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("Set OPENAI_API_KEY in your environment first (use a fresh key).")

    try:
        from llama_index.core import Document, Settings, VectorStoreIndex
        from llama_index.embeddings.openai import OpenAIEmbedding
    except ImportError:
        sys.exit('LlamaIndex not installed. Run:  python -m pip install "llama-index>=0.11"')

    Settings.llm = None  # pure retrieval — no generation step, no LLM needed
    Settings.embed_model = OpenAIEmbedding(model=args.embed_model)

    suppliers = json.loads(CORPUS.read_text())
    suppliers = suppliers if isinstance(suppliers, list) else suppliers.get("suppliers", suppliers)
    if args.limit:
        suppliers = suppliers[: args.limit]
    print(f"Indexing {len(suppliers)} suppliers with {args.embed_model} ...")
    docs = [
        Document(text=supplier_document(s), metadata={"supplier_id": str(s["id"])})
        for s in suppliers
    ]
    index = VectorStoreIndex.from_documents(docs, show_progress=True)
    retriever = index.as_retriever(similarity_top_k=args.top_k)

    queries = json.loads(BENCH.read_text())
    rows, by_tier = [], {}
    for q in queries:
        rel = set(q["ground_truth_supplier_ids"])
        nodes = retriever.retrieve(q["raw_query"])
        top = [n.metadata["supplier_id"] for n in nodes][: args.top_k]
        p5 = precision_at_k(top, rel)
        rows.append({
            "raw_query": q["raw_query"], "difficulty": q["difficulty"],
            "retrieved_ids": top, "precision_at_5": p5,
            "recall_at_5": recall_at_k(top, rel), "reciprocal_rank": reciprocal_rank(top, rel),
        })
        by_tier.setdefault(q["difficulty"], []).append(p5)
        print(f"  [{q['difficulty']:6}] P@5={p5:.2f}  {q['raw_query'][:58]}")

    overall = statistics.mean(r["precision_at_5"] for r in rows)
    mrr = statistics.mean(r["reciprocal_rank"] for r in rows)
    tiers = {t: round(statistics.mean(v), 3) for t, v in by_tier.items()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "system": "offtheshelf_rag_llamaindex", "embed_model": args.embed_model,
        "top_k": args.top_k, "precision_at_5": overall, "mrr": mrr,
        "precision_at_5_by_tier": tiers, "per_query": rows,
    }, indent=2))

    print("\n" + "=" * 60)
    print(f"Off-the-shelf RAG (LlamaIndex)  Precision@5 = {overall:.3f}   MRR = {mrr:.3f}")
    print(f"  by tier: {tiers}")
    print(f"  wrote {OUT.relative_to(ROOT)}")
    print("\nReady-to-paste row for Table 5.8 (Measured multi-constraint Precision@5):")
    print(f"| Off-the-shelf RAG (LlamaIndex) | {overall:.3f} |")


if __name__ == "__main__":
    main()
