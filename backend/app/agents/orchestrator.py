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
import time
import uuid as _uuid
from typing import Any, Literal, Optional

from langgraph.graph import StateGraph, END

from app.agents.state import AgentState
from app.agents.audit_log import append_audit_entry
from app.agents.parser_agent import ParserAgent
from app.agents.tools import build_user_registry
from app.agents.external_discovery_agent import ExternalDiscoveryAgent
from app.agents.discovery_agent import DiscoveryAgent
from app.agents.compliance_agent import ComplianceAgent
from app.agents.ranking_agent import RankingAgent
from app.agents.evaluator_agent import EvaluatorAgent

logger = logging.getLogger(__name__)


def _create_initial_state(
    raw_query: str,
    query_id: str,
    user_id: str,
    search_scope: str,
    *,
    turn_number: int = 1,
    previous_partial_constraints: Optional[dict] = None,
) -> AgentState:
    """Create initial AgentState with all defaults.

    Task 3.3 — turn_number and previous_partial_constraints are populated
    only on resume_pipeline() calls; first-turn submissions leave them at
    their defaults.
    """
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

        # Task 3.3 — clarification dialogue
        clarification_id=None,
        turn_number=turn_number,
        previous_partial_constraints=previous_partial_constraints,

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
    # Per-Task 3.2, the Parser is user-scoped at construction so the
    # closure-bound `lookup_past_query` tool can only ever see this user's
    # memory. If memory infra is unreachable, fall back to the default
    # registry (whose lookup tool is the no-op stub) so the Parser still
    # runs end-to-end.
    user_id = state.get("user_id") or ""
    try:
        registry = build_user_registry(user_id=user_id)
        agent = ParserAgent(tool_registry=registry)
    except Exception as e:  # noqa: BLE001 — never fail the Parser on memory init
        logger.warning(
            "[orchestrator] build_user_registry failed (%s); falling back to "
            "the default tool registry without semantic memory.",
            e,
        )
        agent = ParserAgent()

    state = agent.run(state)

    # Task 3.3 — persist pause state when the Parser raised a clarification
    # on a clean `finish` termination, or via the Task 3.4 pre-loop gate
    # (contentless query, no ReAct run). The fallback/degraded paths also
    # set needs_clarification=True but those carry no resumable state —
    # they just degrade gracefully — so we skip persistence there.
    if state.get("needs_clarification") and state.get("react_terminated_by") in (
        "finish",
        "pre_loop_clarification",
    ):
        try:
            _persist_clarification_for_state(state)
        except Exception as e:  # noqa: BLE001 — persistence must never crash pipeline
            logger.error(
                "[orchestrator] failed to persist pending_clarification for "
                "query_id=%s: %s",
                state.get("query_id"), e,
            )

    return state


def _persist_clarification_for_state(state: AgentState) -> None:
    """Write one pending_clarifications row from the current paused state.

    Populates state["clarification_id"] in-place so the API layer can hand
    it back to the user.
    """
    from app.db.session import SyncSessionLocal
    from app.db.repositories.clarification_repo import (
        persist_pending_clarification_sync,
        MAX_CLARIFICATION_TURNS,
    )

    query_id = state.get("query_id")
    user_id = state.get("user_id")
    if not query_id or not user_id:
        logger.warning(
            "[orchestrator] cannot persist clarification: missing query_id/user_id"
        )
        return

    turn_number = int(state.get("turn_number") or 1)
    if turn_number > MAX_CLARIFICATION_TURNS:
        logger.warning(
            "[orchestrator] turn_number=%d exceeds cap=%d; refusing to persist",
            turn_number, MAX_CLARIFICATION_TURNS,
        )
        return

    with SyncSessionLocal() as db:
        pc_id = persist_pending_clarification_sync(
            db,
            query_id=_uuid.UUID(str(query_id)),
            user_id=_uuid.UUID(str(user_id)),
            raw_query=state.get("raw_query") or "",
            clarification_question=state.get("clarification_question") or "",
            partial_constraints=dict(state.get("parsed_constraints") or {}),
            react_trace=list(state.get("react_trace") or []),
            turn_number=turn_number,
        )
    state["clarification_id"] = str(pc_id)
    logger.info(
        "[orchestrator] Persisted pending_clarification id=%s turn=%d query=%s",
        pc_id, turn_number, query_id,
    )


def finalize_node(state: AgentState) -> AgentState:
    """Pipeline-completion hook (Task 3.2 / Component B).

    Persists a query to long-term memory only when the Evaluator accepted
    the run. Memory write failures NEVER propagate — the user response is
    the critical path; memory is progressive enhancement.
    """
    verdict = (state.get("evaluator_verdict") or "").lower()
    if verdict not in {"accepted", "accept", "auto_accept"}:
        # Don't remember rejected, retried, or failed queries.
        return state

    user_id = state.get("user_id") or ""
    raw_query = state.get("raw_query") or ""
    constraints = state.get("parsed_constraints") or {}
    if not user_id or not raw_query or not constraints:
        return state

    start = time.time()
    try:
        from app.services.query_memory import get_memory_service

        memory_id = get_memory_service().write(
            user_id=str(user_id),
            query_text=raw_query,
            parsed_constraints=dict(constraints),
        )
        duration_ms = int((time.time() - start) * 1000)
        logger.info(
            "[finalize] Wrote query memory user=%s memory_id=%s (%dms)",
            user_id,
            memory_id,
            duration_ms,
        )
        _append_audit(
            state,
            agent_name="memory_service",
            action="memory_written",
            duration_ms=duration_ms,
            reasoning=(
                f"Stored query for future semantic recall, memory_id={memory_id}"
            ),
            output_summary=f"memory_id={memory_id}",
        )
    except Exception as e:  # noqa: BLE001 — memory write must be failsafe
        duration_ms = int((time.time() - start) * 1000)
        logger.warning("[finalize] memory_write_failed: %s", e)
        _append_audit(
            state,
            agent_name="memory_service",
            action="memory_write_failed",
            duration_ms=duration_ms,
            reasoning=str(e),
            output_summary=f"FAILED: {type(e).__name__}",
        )
    return state


def _append_audit(
    state: AgentState,
    *,
    agent_name: str,
    action: str,
    duration_ms: int,
    reasoning: str,
    output_summary: str,
) -> None:
    """Lightweight audit-log appender for the finalize_node (no BaseAgent
    indirection because finalize is a free function, not an agent)."""
    append_audit_entry(
        state,
        agent_name=agent_name,
        action=action,
        input_summary="",
        output_summary=output_summary,
        duration_ms=duration_ms,
        reasoning=reasoning,
    )


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
        # On a retry pass (evaluator already looped us back once), never bounce
        # to external_discovery again — re-running the web stage is the doubling
        # cost Task 1.6 Component A caps. Accept the empty result and end.
        if state.get("evaluator_retries", 0) > 0:
            logger.info("[orchestrator] Routing to END: no candidates on retry pass (external_discovery not re-run)")
            return END

        # First-pass auto-fallback: if we only searched approved and found
        # nothing, expand scope to 'both' and discover from the web once.
        if state.get("search_scope") == "approved_only":
            logger.info("[orchestrator] No approved suppliers found. Auto-expanding scope to 'both'")
            state["search_scope"] = "both"
            # We must run external discovery now to find new suppliers
            return "external_discovery_node"

        logger.info("[orchestrator] Routing to END: no candidates found even in 'both' scope")
        return END

    return "compliance_node"


def after_evaluator(state: AgentState) -> Literal["discovery_node", "finalize_node", "__end__"]:
    if state.get("evaluator_should_retry"):
        n_candidates = len(state.get("candidate_supplier_ids", []))
        logger.info(
            "[orchestrator] Retry pass: skipping external_discovery, "
            "reusing %d candidates from first pass",
            n_candidates,
        )
        return "discovery_node"
    return "finalize_node"


# ── Build the graph ───────────────────────────────────────────────────
def build_pipeline():
    graph = StateGraph(AgentState)

    graph.add_node("parser_node", parser_node)
    graph.add_node("external_discovery_node", external_discovery_node)
    graph.add_node("discovery_node", discovery_node)
    graph.add_node("compliance_node", compliance_node)
    graph.add_node("ranking_node", ranking_node)
    graph.add_node("evaluator_node", evaluator_node)
    graph.add_node("finalize_node", finalize_node)

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
        {
            "discovery_node": "discovery_node",
            "finalize_node": "finalize_node",
        },
    )
    graph.add_edge("finalize_node", END)

    return graph.compile()


_compiled_pipeline = None


def get_pipeline():
    global _compiled_pipeline
    if _compiled_pipeline is None:
        _compiled_pipeline = build_pipeline()
        logger.info("[orchestrator] Pipeline v3 compiled (production v2 architecture)")
    return _compiled_pipeline


async def run_pipeline(
    raw_query: str,
    query_id: str,
    user_id: str,
    search_scope: str = "approved_only",
    *,
    turn_number: int = 1,
    previous_partial_constraints: Optional[dict] = None,
) -> AgentState:
    """
    Main entry point for running the full agent pipeline.

    Args:
        raw_query: The user's natural-language procurement query
        query_id: UUID of the Query record in PostgreSQL
        user_id: UUID of the requesting user
        search_scope: 'approved_only' or 'both'
        turn_number: Task 3.3 — 1 on first submission, 2/3 on resumed turns.
        previous_partial_constraints: Task 3.3 — hint for the Parser on resume.

    Returns:
        Final AgentState with ranked_suppliers and audit_log populated
    """
    logger.info(
        "[orchestrator] Starting pipeline for query_id=%s, scope=%s, turn=%d: %r",
        query_id, search_scope, turn_number, raw_query[:80],
    )

    initial_state = _create_initial_state(
        raw_query,
        query_id,
        user_id,
        search_scope,
        turn_number=turn_number,
        previous_partial_constraints=previous_partial_constraints,
    )
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


async def resume_pipeline(
    clarification_id: str,
    user_answer: str,
) -> AgentState:
    """Task 3.3 — Resume a paused pipeline after the user answers.

    Loads the persisted pending_clarifications row, marks it resolved,
    augments the original query with the user's answer, and re-enters
    the pipeline with turn_number incremented. The Parser may either
    finish on this turn or raise another clarification, up to the
    3-turn DB-enforced cap.

    Raises:
        ValueError: if the clarification row is missing, already resolved,
            or would exceed the max-turns cap.
    """
    from app.db.session import SyncSessionLocal
    from app.db.repositories.clarification_repo import (
        get_pending_clarification_sync,
        mark_resolved_sync,
        MAX_CLARIFICATION_TURNS,
        MaxTurnsReached,
        ClarificationAlreadyResolved,
    )

    try:
        pc_uuid = _uuid.UUID(str(clarification_id))
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid clarification_id: {clarification_id!r}") from e

    def _load_and_mark() -> dict[str, Any]:
        from app.db.models import Query

        with SyncSessionLocal() as db:
            pc = get_pending_clarification_sync(db, pc_uuid)
            if pc is None:
                raise ValueError(f"No pending clarification: {clarification_id}")
            if pc.resolved_at is not None:
                raise ClarificationAlreadyResolved(
                    f"Clarification {clarification_id} already resolved"
                )
            next_turn = int(pc.turn_number) + 1
            if next_turn > MAX_CLARIFICATION_TURNS:
                raise MaxTurnsReached(
                    f"Cannot resume: next turn {next_turn} exceeds cap "
                    f"{MAX_CLARIFICATION_TURNS}."
                )
            # Preserve the original submission's search scope so a resumed
            # 'both'-scoped query doesn't silently fall back to approved_only.
            original_query = db.get(Query, pc.query_id)
            search_scope = (
                original_query.search_scope
                if original_query is not None
                else "approved_only"
            )
            mark_resolved_sync(
                db,
                clarification_id=pc_uuid,
                user_answer=user_answer,
            )
            return {
                "query_id": str(pc.query_id),
                "user_id": str(pc.user_id),
                "raw_query": pc.raw_query,
                "partial_constraints": dict(pc.partial_constraints or {}),
                "turn_number": next_turn,
                "search_scope": search_scope,
            }

    payload = await asyncio.get_running_loop().run_in_executor(None, _load_and_mark)

    augmented_query = (
        f"{payload['raw_query']}\n\nUser clarification: {user_answer.strip()}"
    )
    return await run_pipeline(
        augmented_query,
        payload["query_id"],
        payload["user_id"],
        search_scope=payload["search_scope"],
        turn_number=payload["turn_number"],
        previous_partial_constraints=payload["partial_constraints"],
    )
