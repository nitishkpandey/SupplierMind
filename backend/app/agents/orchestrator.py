"""
app/agents/orchestrator.py — LangGraph state machine wiring all agents.

UPDATED PIPELINE (Phase 8):

  START
    │
    ▼
  [parser_node]
    │ (clarification needed? → END)
    │
    ▼
  [external_discovery_node]   ← NEW: discovers new suppliers from web
    │
    ▼
  [internal_discovery_node]   ← existing: searches enriched DB
    │ (no results? → END)
    │
    ▼
  [compliance_node]
    │
    ▼
  [ranking_node]
    │
    ▼
  END
"""

import asyncio
import logging
from typing import Literal

from langgraph.graph import StateGraph, END

from app.agents.state import AgentState
from app.agents.parser_agent import ParserAgent
from app.agents.external_discovery_agent import ExternalDiscoveryAgent
from app.agents.discovery_agent import DiscoveryAgent
from app.agents.compliance_agent import ComplianceAgent
from app.agents.ranking_agent import RankingAgent

logger = logging.getLogger(__name__)


def _create_initial_state(raw_query: str, query_id: str, user_id: str) -> AgentState:
    """Create initial AgentState with all defaults."""
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
        # External Discovery defaults
        newly_discovered_supplier_ids=[],
        external_discovery_stats={},
        # Internal Discovery defaults
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
def parser_node(state: AgentState) -> AgentState:
    return ParserAgent().run(state)

def external_discovery_node(state: AgentState) -> AgentState:
    return ExternalDiscoveryAgent().run(state)

def discovery_node(state: AgentState) -> AgentState:
    return DiscoveryAgent().run(state)

def compliance_node(state: AgentState) -> AgentState:
    return ComplianceAgent().run(state)

def ranking_node(state: AgentState) -> AgentState:
    return RankingAgent().run(state)


# ── Conditional edges ──────────────────────────────────────────────────
def after_parser(state: AgentState) -> Literal["external_discovery_node", "__end__"]:
    if state.get("needs_clarification") or state.get("error"):
        logger.info("[orchestrator] Routing to END: clarification or error")
        return END
    return "external_discovery_node"


def after_external_discovery(state: AgentState) -> Literal["discovery_node", "__end__"]:
    """Always proceed to internal discovery even if external found nothing."""
    if state.get("error"):
        logger.info("[orchestrator] Routing to END: external discovery error")
        return END
    return "discovery_node"


def after_discovery(state: AgentState) -> Literal["compliance_node", "__end__"]:
    if state.get("error") or not state.get("candidate_supplier_ids"):
        logger.info("[orchestrator] Routing to END: no candidates found")
        return END
    return "compliance_node"


# ── Build the graph ───────────────────────────────────────────────────
def build_pipeline():
    graph = StateGraph(AgentState)

    graph.add_node("parser_node", parser_node)
    graph.add_node("external_discovery_node", external_discovery_node)
    graph.add_node("discovery_node", discovery_node)
    graph.add_node("compliance_node", compliance_node)
    graph.add_node("ranking_node", ranking_node)

    graph.set_entry_point("parser_node")

    graph.add_conditional_edges(
        "parser_node",
        after_parser,
        {"external_discovery_node": "external_discovery_node", END: END},
    )
    graph.add_conditional_edges(
        "external_discovery_node",
        after_external_discovery,
        {"discovery_node": "discovery_node", END: END},
    )
    graph.add_conditional_edges(
        "discovery_node",
        after_discovery,
        {"compliance_node": "compliance_node", END: END},
    )

    graph.add_edge("compliance_node", "ranking_node")
    graph.add_edge("ranking_node", END)

    return graph.compile()


_compiled_pipeline = None


def get_pipeline():
    global _compiled_pipeline
    if _compiled_pipeline is None:
        _compiled_pipeline = build_pipeline()
        logger.info("[orchestrator] Pipeline compiled (with external discovery)")
    return _compiled_pipeline


async def run_pipeline(raw_query: str, query_id: str, user_id: str) -> AgentState:
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
        query_id, raw_query[:80],
    )

    initial_state = _create_initial_state(raw_query, query_id, user_id)
    pipeline = get_pipeline()

    def _run_sync():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return pipeline.invoke(initial_state)
        finally:
            loop.close()

    final_state = await asyncio.get_event_loop().run_in_executor(None, _run_sync)

    logger.info(
        "[orchestrator] Pipeline completed. status=%s, newly_discovered=%d, results=%d",
        final_state.get("pipeline_status"),
        len(final_state.get("newly_discovered_supplier_ids", [])),
        len(final_state.get("ranked_suppliers", [])),
    )

    return final_state
