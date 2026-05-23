"""
app/agents/orchestrator.py — LangGraph state machine that wires all agents together.

THE GRAPH:
  START
    │
    ▼
  [parser_node]
    │
    ├── needs_clarification? ──► END (return clarification request)
    │
    ▼
  [discovery_node]
    │
    ├── error (0 results after retries)? ──► END (return error)
    │
    ▼
  [compliance_node]
    │
    ▼
  [ranking_node]
    │
    ▼
  END

WHY CONDITIONAL EDGES?
Without conditional edges, the graph always runs all nodes.
With them, the orchestrator can:
1. Stop early if clarification is needed (don't run discovery on vague query)
2. Stop early if discovery finds nothing (don't run compliance on 0 results)
3. (Future) Loop back to discovery if compliance removes all candidates

This is the "dynamic routing" that makes SupplierMind agentic.
"""

import asyncio
import logging
from typing import Literal

from langgraph.graph import StateGraph, END

from app.agents.state import AgentState
from app.agents.parser_agent import ParserAgent
from app.agents.discovery_agent import DiscoveryAgent
from app.agents.compliance_agent import ComplianceAgent
from app.agents.ranking_agent import RankingAgent

logger = logging.getLogger(__name__)


def _create_initial_state(
    raw_query: str,
    query_id: str,
    user_id: str,
) -> AgentState:
    """
    Create the initial state dict passed to the LangGraph pipeline.
    All optional fields must be initialised here.
    LangGraph requires all TypedDict keys to exist at initialisation.
    """
    return AgentState(
        # Input
        raw_query=raw_query,
        query_id=query_id,
        user_id=user_id,
        # Parser defaults
        parsed_constraints=None,
        detected_language="en",
        needs_clarification=False,
        clarification_question=None,
        # Discovery defaults
        candidate_supplier_ids=[],
        semantic_scores={},
        geo_distances={},
        retry_count=0,
        relaxed_constraints=[],
        # Compliance defaults
        compliance_results=[],
        # Ranking defaults
        ranked_suppliers=[],
        # Control
        audit_log=[],
        error=None,
        pipeline_status="running",
    )


# ── Node functions ────────────────────────────────────────────────────
# LangGraph nodes are plain functions: state → state
# Each creates its agent once and calls run()

def parser_node(state: AgentState) -> AgentState:
    return ParserAgent().run(state)

def discovery_node(state: AgentState) -> AgentState:
    return DiscoveryAgent().run(state)

def compliance_node(state: AgentState) -> AgentState:
    return ComplianceAgent().run(state)

def ranking_node(state: AgentState) -> AgentState:
    return RankingAgent().run(state)


# ── Conditional edge functions ────────────────────────────────────────
# These decide where to route AFTER a node completes.
# They read state and return the name of the next node (or END).

def after_parser(
    state: AgentState,
) -> Literal["discovery_node", "__end__"]:
    """
    After parser:
    - If clarification needed → END (UI shows clarification question)
    - If error → END
    - Otherwise → discovery
    """
    if state.get("needs_clarification"):
        logger.info("[orchestrator] Routing to END: clarification needed")
        return END
    if state.get("error"):
        logger.info("[orchestrator] Routing to END: parser error")
        return END
    return "discovery_node"


def after_discovery(
    state: AgentState,
) -> Literal["compliance_node", "__end__"]:
    """
    After discovery:
    - If 0 results (after retries) → END with error message
    - Otherwise → compliance
    """
    if state.get("error") or not state.get("candidate_supplier_ids"):
        logger.info("[orchestrator] Routing to END: no candidates found")
        return END
    return "compliance_node"


# ── Build the graph ───────────────────────────────────────────────────
def build_pipeline() -> StateGraph:
    """
    Constructs and compiles the LangGraph pipeline.
    Returns a compiled app that can be invoked with .invoke(state).

    Called once and cached — building the graph is cheap,
    but we avoid rebuilding it on every query.
    """
    graph = StateGraph(AgentState)

    # Add all nodes
    graph.add_node("parser_node", parser_node)
    graph.add_node("discovery_node", discovery_node)
    graph.add_node("compliance_node", compliance_node)
    graph.add_node("ranking_node", ranking_node)

    # Entry point
    graph.set_entry_point("parser_node")

    # Conditional edges (where to go AFTER each node)
    graph.add_conditional_edges(
        "parser_node",
        after_parser,
        {"discovery_node": "discovery_node", END: END},
    )
    graph.add_conditional_edges(
        "discovery_node",
        after_discovery,
        {"compliance_node": "compliance_node", END: END},
    )

    # Fixed edges (always go to the next node)
    graph.add_edge("compliance_node", "ranking_node")
    graph.add_edge("ranking_node", END)

    return graph.compile()


# Cached compiled pipeline — built once at module import
_compiled_pipeline = None

def get_pipeline():
    """Returns the cached compiled pipeline. Builds it on first call."""
    global _compiled_pipeline
    if _compiled_pipeline is None:
        _compiled_pipeline = build_pipeline()
        logger.info("[orchestrator] Pipeline compiled successfully")
    return _compiled_pipeline


async def run_pipeline(
    raw_query: str,
    query_id: str,
    user_id: str,
) -> AgentState:
    """
    Main entry point for running the full agent pipeline.

    Args:
        raw_query: The user's natural-language procurement query
        query_id: UUID of the Query record in PostgreSQL
        user_id: UUID of the requesting user

    Returns:
        Final AgentState with ranked_suppliers and audit_log populated
    """
    logger.info(
        "[orchestrator] Starting pipeline for query_id=%s: %r",
        query_id, raw_query[:80]
    )

    initial_state = _create_initial_state(raw_query, query_id, user_id)
    pipeline = get_pipeline()

    # Wrap pipeline.invoke to set a consistent event loop for the worker thread.
    # This prevents SQLAlchemy pool errors caused by multiple asyncio.run() calls.
    def _run_sync():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return pipeline.invoke(initial_state)
        finally:
            loop.close()

    final_state = await asyncio.get_event_loop().run_in_executor(
        None, _run_sync
    )

    logger.info(
        "[orchestrator] Pipeline completed. status=%s, results=%d",
        final_state.get("pipeline_status"),
        len(final_state.get("ranked_suppliers", [])),
    )

    return final_state
