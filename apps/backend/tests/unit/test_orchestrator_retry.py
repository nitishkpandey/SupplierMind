"""Task 1.6 Component A — evaluator retry-loop cap.

The evaluator retry must never re-run external_discovery (the expensive web
stage). It loops back to discovery_node only, reusing the candidate pool from
the first pass. These tests pin the routing/logging contract so a future graph
edit cannot silently re-introduce the doubling cost.

Pure routing-function tests — no pipeline execution, no LLM/network.
"""

import logging

from langgraph.graph import END

from app.agents.orchestrator import after_discovery, after_evaluator


# ── after_evaluator ──────────────────────────────────────────────────
def test_retry_routes_to_discovery_not_external():
    state = {"evaluator_should_retry": True, "candidate_supplier_ids": ["a", "b", "c"]}
    assert after_evaluator(state) == "discovery_node"


def test_no_retry_routes_to_finalize():
    # Task 3.2: instead of routing directly to END, a non-retry pass now
    # routes through the finalize_node so the memory write hook can fire.
    # The finalize_node itself terminates the graph (graph.add_edge → END).
    state = {"evaluator_should_retry": False, "candidate_supplier_ids": ["a"]}
    assert after_evaluator(state) == "finalize_node"


def test_retry_logs_reuse_line_with_candidate_count(caplog):
    state = {"evaluator_should_retry": True, "candidate_supplier_ids": ["a", "b", "c", "d"]}
    with caplog.at_level(logging.INFO, logger="app.agents.orchestrator"):
        after_evaluator(state)
    msg = "\n".join(r.getMessage() for r in caplog.records)
    assert "skipping external_discovery" in msg
    assert "reusing 4 candidates" in msg


# ── after_discovery ──────────────────────────────────────────────────
def test_first_pass_no_candidates_falls_back_to_external():
    # First pass (no evaluator retry yet): approved_only with zero candidates
    # must still expand to web discovery — existing behavior preserved.
    state = {
        "candidate_supplier_ids": [],
        "search_scope": "approved_only",
        "evaluator_retries": 0,
    }
    assert after_discovery(state) == "external_discovery_node"
    assert state["search_scope"] == "both"


def test_retry_pass_no_candidates_ends_without_external():
    # On a retry pass, zero candidates must NOT bounce back to external
    # discovery — that is the doubling we are capping. Route to END instead.
    state = {
        "candidate_supplier_ids": [],
        "search_scope": "approved_only",
        "evaluator_retries": 1,
    }
    assert after_discovery(state) == END


def test_candidates_route_to_compliance():
    state = {
        "candidate_supplier_ids": ["x"],
        "search_scope": "both",
        "evaluator_retries": 0,
    }
    assert after_discovery(state) == "compliance_node"
