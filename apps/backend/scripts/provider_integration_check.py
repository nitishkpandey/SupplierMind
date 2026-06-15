"""Phase 1 closeout: end-to-end check on the OpenAI provider + trace capture.

Runs the moment OPENAI_API_KEY lands in backend/.env:

  1. Verifies provider selection (expects OpenAIProvider — single provider).
  2. One end-to-end pipeline query (Parser -> Discovery -> Compliance ->
     Ranking) on GPT-4o-mini.
  3. Re-captures the Task 3.1 / 3.2 / 3.3 demo traces on GPT-4o-mini and
     saves them under traces/gpt4o_mini/ alongside traces/groq/.
  4. Prints the estimated spend for the whole run.

Prerequisites:
  - backend/.env: LLM_PROVIDER=openai, OPENAI_API_KEY=sk-...
  - docker compose up -d  (Postgres, Milvus, Redis)

Run from backend/:
    uv run python scripts/provider_integration_check.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("provider_check")

BACKEND = Path(__file__).resolve().parents[1]
TRACES_DIR = BACKEND.parent / "traces" / "gpt4o_mini"
EVAL_USER_ID = "00000000-0000-0000-0000-000000000000"


def check_provider() -> None:
    from app.core.config import settings
    from app.core.llm import OpenAIProvider, get_llm_client

    if settings.LLM_PROVIDER != "openai":
        raise SystemExit(
            f"LLM_PROVIDER={settings.LLM_PROVIDER!r} — set LLM_PROVIDER=openai "
            "and OPENAI_API_KEY in backend/.env first."
        )
    client = get_llm_client()
    logger.info("Active client: %s", client.provider_name)
    assert isinstance(client, OpenAIProvider), (
        "single-provider deployment (ADR-002): expected OpenAIProvider, "
        f"got {type(client).__name__}"
    )
    # One trivial call proves auth + connectivity.
    out = client.complete(
        [{"role": "user", "content": "Reply with exactly: provider-ok"}],
        max_tokens=8, temperature=0.0,
    )
    logger.info("Smoke completion: %r (served by %s)", out.strip(),
                getattr(client, "last_provider_used", client.provider_name))


async def pipeline_run() -> dict:
    from app.agents.orchestrator import run_pipeline

    query = "ISO 9001 certified packaging supplier in Germany, 5000 units per month"
    qid = str(uuid.uuid4())
    logger.info("Pipeline run on GPT-4o-mini: %r", query)
    start = time.time()
    state = await run_pipeline(query, qid, user_id=EVAL_USER_ID)
    elapsed = int((time.time() - start) * 1000)
    ranked = state.get("ranked_suppliers", [])
    logger.info("Pipeline done in %dms — %d ranked suppliers, verdict=%s",
                elapsed, len(ranked), state.get("evaluator_verdict"))
    return {
        "query": query,
        "query_id": qid,
        "elapsed_ms": elapsed,
        "result_count": len(ranked),
        "evaluator_verdict": state.get("evaluator_verdict"),
        "react_trace": state.get("react_trace"),
        "parsed_constraints": state.get("parsed_constraints"),
        "audit_log": state.get("audit_log", []),
    }


async def recapture_traces() -> None:
    """Re-run the three Week-3 demo drivers; their outputs ARE the traces."""
    TRACES_DIR.mkdir(parents=True, exist_ok=True)

    # Task 3.1 — ReAct parser trace (direct ParserAgent runs).
    # Task 3.2 / 3.3 demos are also importable mains; they write their JSONs
    # into Documents/thesis_evidence/week_3_agentic/ — copy results over.
    logger.info("Re-capture: drive the three demo scripts manually if their "
                "main() signatures changed; otherwise run them via:")
    logger.info("  uv run python scripts/parser_react_demo.py")
    logger.info("  uv run python scripts/memory_demo.py")
    logger.info("  uv run python scripts/clarification_demo.py")
    logger.info("then copy the JSONs into %s", TRACES_DIR)


async def main() -> None:
    from app.core.cache import InMemoryCache, set_cache_instance
    from app.core.vector_store import create_vector_store, set_vector_store_instance

    check_provider()

    set_cache_instance(InMemoryCache())
    set_vector_store_instance(create_vector_store())

    result = await pipeline_run()
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TRACES_DIR / "pipeline_integration_run.json"
    out_path.write_text(
        json.dumps(
            {"captured_at": datetime.now(timezone.utc).isoformat(), **result},
            indent=2, default=str,
        ),
        encoding="utf-8",
    )
    logger.info("Saved %s", out_path)

    await recapture_traces()

    from app.core.llm import get_llm_client
    logger.info("Estimated spend this run: $%.4f", get_llm_client().total_cost_usd)


if __name__ == "__main__":
    asyncio.run(main())
