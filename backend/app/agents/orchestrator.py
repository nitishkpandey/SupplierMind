"""
app/agents/orchestrator.py — LangGraph state machine wiring all agents.

PRODUCTION V2 PIPELINE:

  START
    │
    ▼
  [parser_node]
    │ (clarification needed? → END)
    │
    ├─ (scope == 'approved_only')
    │      │
    │      ▼
    │   (skip external)
    │      │
    ├─ (scope == 'both')
    │      │
    │      ▼
  [external_discovery_node]
    │      │
    │      ▼
    └──────┴────────┐
                    │
                    ▼
          [internal_discovery_node]
                    │ (no results AND scope == 'approved_only'? → fallback to 'both')
                    │ (no results? → END)
                    │
                    ▼
             [compliance_node]
                    │
                    ▼
              [ranking_node]
                    │
                    ▼
             [evaluator_node]
                    │ (should_retry? → internal_discovery_node)
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
from app.agents.evaluator_agent import EvaluatorAgent

logger = logging.getLogger(__name__)


def _create_initial_state(
    raw_query: str, query_id: str, user_id: str, search_scope: str
) -> AgentState:
    """Create initial AgentState with all defaults."""
    return AgentState(
        # Input
        raw_query=raw_query,
        query_id=query_id,
        user_id=user_id,
        search_scope=search_scope,

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
        tier_assignments={},

        # Compliance defaults
        compliance_results=[],

        # Ranking defaults
        ranked_suppliers=[],

        # Evaluator defaults
        evaluator_retries=0,
        evaluator_verdict=None,
        evaluator_should_retry=False,

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


def evaluator_node(state: AgentState) -> AgentState:
    return EvaluatorAgent().run(state)


# ── Conditional edges ──────────────────────────────────────────────────
def after_parser(state: AgentState) -> Literal["external_discovery_node", "discovery_node", "__end__"]:
    if state.get("needs_clarification") or state.get("error"):
        logger.info("[orchestrator] Routing to END: clarification or error")
        return END

    if state.get("search_scope") == "approved_only":
        logger.info("[orchestrator] Scope is approved_only — skipping external discovery")
        return "discovery_node"

    return "external_discovery_node"


def after_external_discovery(state: AgentState) -> Literal["discovery_node", "__end__"]:
    if state.get("error"):
        logger.info("[orchestrator] Routing to END: external discovery error")
        return END
    return "discovery_node"


def after_discovery(state: AgentState) -> Literal["external_discovery_node", "compliance_node", "__end__"]:
    if state.get("error"):
        logger.info("[orchestrator] Routing to END: discovery error")
        return END

    if not state.get("candidate_supplier_ids"):
        # Auto-fallback: if we only searched approved and found nothing, expand scope to 'both'
        if state.get("search_scope") == "approved_only":
            logger.info("[orchestrator] No approved suppliers found. Auto-expanding scope to 'both'")
            state["search_scope"] = "both"
            # We must run external discovery now to find new suppliers
            return "external_discovery_node"

        logger.info("[orchestrator] Routing to END: no candidates found even in 'both' scope")
        return END

    return "compliance_node"


def after_evaluator(state: AgentState) -> Literal["discovery_node", "__end__"]:
    if state.get("evaluator_should_retry"):
        logger.info("[orchestrator] Evaluator requested retry — looping back to discovery")
        return "discovery_node"
    return END


# ── Build the graph ───────────────────────────────────────────────────
def build_pipeline():
    graph = StateGraph(AgentState)

    graph.add_node("parser_node", parser_node)
    graph.add_node("external_discovery_node", external_discovery_node)
    graph.add_node("discovery_node", discovery_node)
    graph.add_node("compliance_node", compliance_node)
    graph.add_node("ranking_node", ranking_node)
    graph.add_node("evaluator_node", evaluator_node)

    graph.set_entry_point("parser_node")

    graph.add_conditional_edges(
        "parser_node",
        after_parser,
        {
            "external_discovery_node": "external_discovery_node",
            "discovery_node": "discovery_node",
            END: END
        },
    )

    graph.add_conditional_edges(
        "external_discovery_node",
        after_external_discovery,
        {"discovery_node": "discovery_node", END: END},
    )

    graph.add_conditional_edges(
        "discovery_node",
        after_discovery,
        {
            "external_discovery_node": "external_discovery_node",
            "compliance_node": "compliance_node",
            END: END
        },
    )

    graph.add_edge("compliance_node", "ranking_node")
    graph.add_edge("ranking_node", "evaluator_node")

    graph.add_conditional_edges(
        "evaluator_node",
        after_evaluator,
        {"discovery_node": "discovery_node", END: END},
    )

    return graph.compile()


_compiled_pipeline = None


def get_pipeline():
    global _compiled_pipeline
    if _compiled_pipeline is None:
        _compiled_pipeline = build_pipeline()
        logger.info("[orchestrator] Pipeline v3 compiled (production v2 architecture)")
    return _compiled_pipeline


async def run_pipeline(
    raw_query: str, query_id: str, user_id: str, search_scope: str = "approved_only"
) -> AgentState:
    """
    Main entry point for running the full agent pipeline.

    Args:
        raw_query: The user's natural-language procurement query
        query_id: UUID of the Query record in PostgreSQL
        user_id: UUID of the requesting user
        search_scope: 'approved_only' or 'both'

    Returns:
        Final AgentState with ranked_suppliers and audit_log populated
    """
    logger.info(
        "[orchestrator] Starting pipeline for query_id=%s, scope=%s: %r",
        query_id, search_scope, raw_query[:80],
    )

    initial_state = _create_initial_state(raw_query, query_id, user_id, search_scope)
    pipeline = get_pipeline()

    # The LangGraph pipeline uses synchronous tools and database access.
    # To avoid blocking the FastAPI event loop or dealing with nested event loops,
    # we run the entire graph in a thread pool executor.
    def _run_sync():
        return pipeline.invoke(initial_state)

    final_state = await asyncio.get_running_loop().run_in_executor(None, _run_sync)

    logger.info(
        "[orchestrator] Pipeline completed. status=%s, scope=%s, results=%d",
        final_state.get("pipeline_status"),
        final_state.get("search_scope"),
        len(final_state.get("ranked_suppliers", [])),
    )

    return final_state
