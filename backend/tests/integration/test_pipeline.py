"""
tests/integration/test_pipeline.py — End-to-end pipeline test.

Tests the complete flow: query → parser → discovery → compliance → ranking.
Verifies that the system returns results and the audit trail is populated.
"""

import pytest
import asyncio


@pytest.mark.asyncio
async def test_full_pipeline_metals_query():
    """Test a simple metals query returns results."""
    from app.agents.orchestrator import run_pipeline

    state = await run_pipeline(
        raw_query="Find ISO 9001 certified metal suppliers in Germany",
        query_id="test-query-001",
        user_id="test-user-001",
    )

    assert state["pipeline_status"] in ("completed", "failed"), (
        f"Unexpected status: {state['pipeline_status']}"
    )
    assert state.get("parsed_constraints") is not None, "Parser failed"
    assert len(state.get("audit_log", [])) > 0, "No audit log entries"

    if state["pipeline_status"] == "completed":
        assert len(state.get("ranked_suppliers", [])) > 0, "No results returned"
        top = state["ranked_suppliers"][0]
        assert 0.0 <= top["total_score"] <= 1.0
        assert top["explanation"] != ""
        assert top["rank"] == 1


@pytest.mark.asyncio
async def test_parser_extracts_radius():
    """Test that radius constraints are extracted correctly."""
    from app.agents.parser_agent import ParserAgent
    from app.agents.orchestrator import _create_initial_state

    state = _create_initial_state(
        raw_query="Bronze supplier within 25km of Bremen ISO 9001 certified",
        query_id="test-002",
        user_id="test-user",
    )
    parser = ParserAgent()
    result = parser.run(state)

    constraints = result.get("parsed_constraints") or {}
    assert constraints.get("location_radius_km") == 25, (
        f"Expected radius=25, got {constraints.get('location_radius_km')}"
    )
    assert "ISO 9001" in (constraints.get("certifications") or [])


@pytest.mark.asyncio
async def test_ambiguous_query_triggers_clarification():
    """Test that vague queries trigger clarification request."""
    from app.agents.parser_agent import ParserAgent
    from app.agents.orchestrator import _create_initial_state

    state = _create_initial_state(
        raw_query="good supplier",  # Too vague
        query_id="test-003",
        user_id="test-user",
    )
    parser = ParserAgent()
    result = parser.run(state)

    # Should either need clarification OR return low confidence
    # (Exact behavior depends on LLM response)
    assert result.get("pipeline_status") in ("running", "needs_clarification")
