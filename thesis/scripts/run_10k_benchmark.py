"""
thesis/scripts/run_10k_benchmark.py

Runs the three paradigms (and/or the SQL/manual baselines) against the
10k-grounded SupplierBench, writing results under thesis/results/10k/.

THIS IS THE PAID / SLOW PATH. It calls the LLM + embedding providers and needs
infrastructure up. Prerequisites:
  1. docker compose -f infra/docker/docker-compose.yml up -d   (Postgres + Milvus)
  2. The 10k corpus ingested into Postgres AND Milvus, e.g.:
       cd apps/backend
       uv run python scripts/bulk_ingest_synthetic.py --force-pg --skip-milvus
       uv run python scripts/bulk_ingest_synthetic.py --skip-pg --resume
  3. API keys in apps/backend/.env (OpenAI + Voyage).

It does NOT touch the frozen curated-100 results — outputs go to a separate
folder. Scoring is bound to the 10k supplier IDs, not the curated set.

Examples:
    cd apps/backend
    # one full three-paradigm run
    uv run python ../../thesis/scripts/run_10k_benchmark.py --p1 --p2 --p3
    # 5 repeats of P3 only, for the run-to-run variance experiment
    uv run python ../../thesis/scripts/run_10k_benchmark.py --p3 --runs 5
    # quick smoke on the first 3 queries
    uv run python ../../thesis/scripts/run_10k_benchmark.py --p2 --p3 --limit 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "apps" / "backend"
import sys  # noqa: E402

sys.path.insert(0, str(BACKEND))

BENCHMARK = BACKEND.parent.parent / "thesis" / "benchmark" / "supplierbench25_10k.json"
CORPUS_10K = BACKEND / "data" / "suppliers_synthetic_10k.json"
OUT_DIR = BACKEND.parent.parent / "thesis" / "results" / "10k"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("thesis.run10k")


def corpus_ids() -> list[str]:
    return [str(s["id"]) for s in json.loads(CORPUS_10K.read_text()) if s.get("id")]


async def main() -> None:
    ap = argparse.ArgumentParser(description="Run SupplierBench on the 10k corpus")
    ap.add_argument("--p1", action="store_true", help="single-prompt LLM")
    ap.add_argument("--p2", action="store_true", help="RAG")
    ap.add_argument("--p3", action="store_true", help="SupplierMind agentic")
    ap.add_argument("--baselines", action="store_true", help="keyword + manual SQL baselines")
    ap.add_argument("--limit", type=int, default=None, help="limit queries (smoke test)")
    ap.add_argument("--runs", type=int, default=1, help="repeat N times for variance")
    ap.add_argument("--abstention", action="store_true",
                    help="run the Abstention-5 set (unsatisfiable queries) instead of SupplierBench-25")
    ap.add_argument("--ablation", default="none",
                    help="P3 component ablation: 'none' (full) or 'no_compliance'")
    args = ap.parse_args()

    if not (args.p1 or args.p2 or args.p3 or args.baselines):
        ap.error("pick at least one of --p1 --p2 --p3 --baselines")

    bench_file = (
        BENCHMARK.parent / "abstention5_10k.json" if args.abstention else BENCHMARK
    )
    if args.abstention:
        out_dir = OUT_DIR.parent / "10k_abstention"
    elif args.ablation != "none":
        out_dir = OUT_DIR.parent / f"10k_ablation_{args.ablation}"
    else:
        out_dir = OUT_DIR
    if not bench_file.exists():
        ap.error(f"benchmark not found: {bench_file} (run build_benchmark_10k.py first)")

    ids = corpus_ids()
    logger.info("10k corpus allowlist: %d supplier IDs", len(ids))

    # vector store + cache, same setup the stock runner uses
    if args.p2 or args.p3:
        from app.core.cache import InMemoryCache, set_cache_instance
        from app.core.vector_store import create_vector_store, set_vector_store_instance

        set_cache_instance(InMemoryCache())
        vs = create_vector_store()
        set_vector_store_instance(vs)
        count = vs.count()
        logger.info("Vector store ready: %d entities indexed", count)
        if count < len(ids):
            logger.warning(
                "Milvus has %d entities but the 10k corpus has %d — retrieval will be "
                "incomplete. Re-ingest before trusting P2/P3 numbers.", count, len(ids),
            )

    from app.evaluation.runner import run_full_evaluation

    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, args.runs + 1):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        out = out_dir / f"run_{stamp}_r{i}.json"
        ckpt = out_dir / f"checkpoint_r{i}.json"
        logger.info("=== run %d/%d -> %s ===", i, args.runs, out.name)
        await run_full_evaluation(
            run_suppliermind=args.p3,
            run_baselines=args.baselines,
            query_limit=args.limit,
            run_p1=args.p1,
            run_p2=args.p2,
            benchmark_file=bench_file,
            corpus_ids=ids,
            results_file=out,
            checkpoint_file=ckpt,
            ablation=args.ablation,
        )
        logger.info("run %d written: %s", i, out)

    logger.info(
        "Done. Analyze with:\n  python thesis/scripts/analyze_results.py "
        "--results <run>.json --corpus %s --benchmark %s",
        CORPUS_10K, BENCHMARK,
    )


if __name__ == "__main__":
    asyncio.run(main())
