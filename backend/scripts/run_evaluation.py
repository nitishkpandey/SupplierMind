"""
backend/scripts/run_evaluation.py — CLI to run SupplierBench evaluation.

USAGE:
    # Full evaluation (all 25 queries, all 3 systems) — ~15 minutes:
    uv run python scripts/run_evaluation.py

    # Baselines only (fast, for testing metrics):
    uv run python scripts/run_evaluation.py --baselines-only

    # Quick test with first 5 queries:
    uv run python scripts/run_evaluation.py --limit 5

    # Generate report from existing results (no re-running):
    uv run python scripts/run_evaluation.py --report-only
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    parser = argparse.ArgumentParser(description="SupplierBench evaluation runner")
    parser.add_argument(
        "--baselines-only",
        action="store_true",
        help="Run only the two baselines (fast, no LLM calls)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of queries (for testing)",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Generate report from existing results (no evaluation run)",
    )
    args = parser.parse_args()

    if args.report_only:
        logger.info("Generating report from existing results...")
        from app.evaluation.report import generate_thesis_report
        generate_thesis_report()
        return

    # Initialize vector store (required for SupplierMind)
    if not args.baselines_only:
        logger.info("Initializing vector store...")
        from app.core.config import settings
        from app.core.vector_store import create_vector_store, set_vector_store_instance
        from app.core.cache import InMemoryCache, set_cache_instance

        set_cache_instance(InMemoryCache())
        vs = create_vector_store()
        set_vector_store_instance(vs)
        logger.info("Vector store ready: %d suppliers indexed", vs.count())

    logger.info("Starting evaluation...")
    from app.evaluation.runner import run_full_evaluation

    results = await run_full_evaluation(
        run_suppliermind=not args.baselines_only,
        run_baselines=True,
        query_limit=args.limit,
    )

    logger.info("Generating thesis report...")
    from app.evaluation.report import generate_thesis_report
    generate_thesis_report()

    logger.info("Evaluation complete.")


if __name__ == "__main__":
    asyncio.run(main())
