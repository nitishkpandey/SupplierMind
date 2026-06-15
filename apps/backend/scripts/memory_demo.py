"""Drive the Task 3.2 killer demo: cross-query memory hop in the Parser.

Two queries against the live Groq LLM, real Voyage embeddings, real Milvus.

  Q1: ISO 9001 certified packaging supplier in Germany with 10000 units per
      month capacity.
  Q2: Same product as last time but in Bavaria.

Step 1: A throwaway user id is created and any prior memory for it is wiped.
Step 2: Q1 runs through the real ParserAgent (its lookup_past_query tool
        returns [] since no memory exists yet). The resulting parsed
        constraints are persisted to memory directly via QueryMemoryService
        — we skip the full discovery/ranking pipeline because the goal of
        the demo is the Parser-side cross-query reasoning, not supplier
        lookup.
Step 3: Q2 runs through the same Parser construction (build_user_registry
        bound to the same user id). The Parser is expected to call
        lookup_past_query, see Q1's constraints in the Observation, and
        merge them with the new location.

Output: Documents/thesis_evidence/week_3_agentic/memory_demo.json with both
react_trace blocks, parsed constraints, and the verification flags Component
D listed.

Usage:
    uv run python scripts/memory_demo.py
"""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.parser_agent import ParserAgent  # noqa: E402
from app.agents.tools import build_user_registry  # noqa: E402
from app.services.query_memory import get_memory_service  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s %(message)s")
logger = logging.getLogger("memory_demo")

OUT_DIR = (
    Path(__file__).resolve().parents[2]
    / "Documents"
    / "thesis_evidence"
    / "week_3_agentic"
)
OUT_PATH = OUT_DIR / "memory_demo.json"

Q1 = "ISO 9001 certified packaging supplier in Germany with 10000 units per month capacity"
Q2 = "Same product as last time but in Bavaria"


_DEMO_MIN_SIMILARITY = 0.3  # production default is 0.65; see notes.md threshold tuning note


def _run_parser(user_id: str, raw_query: str, query_id: str) -> dict:
    """Run the real Parser end-to-end for `raw_query`, return its output."""
    registry = build_user_registry(
        user_id=user_id,
        lookup_min_similarity=_DEMO_MIN_SIMILARITY,
    )
    parser = ParserAgent(tool_registry=registry)
    state = {
        "raw_query": raw_query,
        "query_id": query_id,
        "user_id": user_id,
        "audit_log": [],
        "search_scope": "approved_only",
    }
    start = time.time()
    out = parser.execute(state)
    elapsed_ms = int((time.time() - start) * 1000)
    audit_entry = (out.get("audit_log") or [{}])[0]
    return {
        "raw_query": raw_query,
        "elapsed_ms": elapsed_ms,
        "terminated_by": out.get("react_terminated_by"),
        "iterations": len(out.get("react_trace") or []),
        "tools_called": [
            s["action"]
            for s in out.get("react_trace") or []
            if s.get("action") and s["action"] != "Finish"
        ],
        "parsed_constraints": out.get("parsed_constraints"),
        "needs_clarification": out.get("needs_clarification"),
        "react_trace": out.get("react_trace"),
        "audit_entry": {
            "action": audit_entry.get("action"),
            "duration_ms": audit_entry.get("duration_ms"),
            "input_snapshot": audit_entry.get("input_snapshot"),
            "output_snapshot": audit_entry.get("output_snapshot"),
        },
    }


def _verify_hop(q2_result: dict, q1_constraints: dict) -> dict:
    """Compute the four assertions Task 3.2 Component D lists for q2_trace."""
    trace = q2_result.get("react_trace") or []
    constraints = q2_result.get("parsed_constraints") or {}

    called_lookup = any(s.get("action") == "lookup_past_query" for s in trace)

    lookup_obs_carried_q1 = False
    for step in trace:
        if step.get("action") != "lookup_past_query":
            continue
        obs = step.get("observation")
        if isinstance(obs, list) and obs:
            hit0 = obs[0] or {}
            cobj = hit0.get("constraints") or {}
            # Q1's load-bearing fields must appear in the observation
            if (
                cobj.get("product_type") == q1_constraints.get("product_type")
                and "ISO 9001" in (cobj.get("certifications") or [])
            ):
                lookup_obs_carried_q1 = True
                break

    later_thought_refs_memory = False
    saw_lookup = False
    for step in trace:
        if step.get("action") == "lookup_past_query":
            saw_lookup = True
            continue
        if saw_lookup:
            thought = (step.get("thought") or "").lower()
            if any(
                tok in thought
                for tok in (
                    "past",
                    "previous",
                    "prior",
                    "last time",
                    "memory",
                    "earlier",
                    "remember",
                )
            ):
                later_thought_refs_memory = True
                break

    finish_merge_ok = (
        constraints.get("product_type") == q1_constraints.get("product_type")
        and "ISO 9001" in (constraints.get("certifications") or [])
        and constraints.get("capacity_min") in (10000, 10000.0)
        and (
            (constraints.get("location_region") or "").lower() == "bavaria"
            or (constraints.get("location_city") or "").lower() == "bavaria"
            or "bavaria" in (constraints.get("location_name") or "").lower()
        )
    )

    return {
        "q2_called_lookup_past_query": called_lookup,
        "q2_observation_carried_q1_constraints": lookup_obs_carried_q1,
        "q2_later_thought_referenced_memory": later_thought_refs_memory,
        "q2_finish_merged_q1_with_q2_location": finish_merge_ok,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    user_id = str(uuid.uuid4())

    memory = get_memory_service()
    pre_deleted = memory.delete_all_for_user(user_id)
    logger.info("Reset memory for user_id=%s (deleted %d rows)", user_id, pre_deleted)

    print("\n== Q1 ==")
    q1 = _run_parser(user_id, Q1, query_id=f"demo-q1-{int(time.time())}")
    print(
        f"  iter={q1['iterations']} terminated_by={q1['terminated_by']} "
        f"latency_ms={q1['elapsed_ms']} tools={q1['tools_called']}"
    )

    # Persist Q1's constraints into memory directly (we are NOT running the
    # full pipeline; finalize_node is what would do this in production).
    q1_constraints = q1["parsed_constraints"] or {}
    if q1_constraints:
        memory_id = memory.write(
            user_id=user_id,
            query_text=Q1,
            parsed_constraints=q1_constraints,
        )
        logger.info("Persisted Q1 to memory: memory_id=%s", memory_id)
    else:
        logger.warning("Q1 parsed no constraints; skipping memory write — Q2 will see []")

    print("\n== Q2 ==")
    q2 = _run_parser(user_id, Q2, query_id=f"demo-q2-{int(time.time())}")
    print(
        f"  iter={q2['iterations']} terminated_by={q2['terminated_by']} "
        f"latency_ms={q2['elapsed_ms']} tools={q2['tools_called']}"
    )

    verification = _verify_hop(q2, q1_constraints)

    payload = {
        "user_id": user_id,
        "q1": q1,
        "q2": q2,
        "verification": verification,
    }
    OUT_PATH.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    print(f"\nSaved: {OUT_PATH}")
    print(json.dumps(verification, indent=2))

    # Cleanup so repeated demo runs don't leave stale memory rows behind.
    cleaned = memory.delete_all_for_user(user_id)
    logger.info("Cleaned %d demo rows for user_id=%s", cleaned, user_id)


if __name__ == "__main__":
    main()
