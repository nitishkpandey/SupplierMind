"""
app/agents/base.py — Base agent class with shared utilities.

WHY A BASE CLASS?
All 5 agents need:
1. An LLM client
2. Audit logging (every agent logs its reasoning)
3. Timing (how long did this agent take?)
4. Error handling (catch, log, set state.error, don't crash)

Writing these 4 things 5 times violates DRY.
BaseAgent writes them once. Each agent inherits.
"""

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from app.agents.audit_log import append_audit_entry
from app.agents.state import AgentState
from app.core.llm import LLMClient, get_llm_client
from app.utils.text_normalization import clean_optional_text

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Abstract base class for all SupplierMind agents.

    Each agent must implement execute() — that's the agent's logic.
    BaseAgent handles timing, logging, and error handling automatically.
    """

    # Subclasses define their name for audit logs
    agent_name: str = "base"

    def __init__(self) -> None:
        self.llm: LLMClient = get_llm_client()

    def run(self, state: AgentState) -> AgentState:
        """
        Entry point called by LangGraph.
        Wraps execute() with timing and error handling.
        Never raises — exceptions are caught and stored in state.error.
        """
        start_time = time.time()

        try:
            updated_state = self.execute(state)
            duration_ms = int((time.time() - start_time) * 1000)
            logger.info("[%s] Completed in %dms", self.agent_name, duration_ms)
            return updated_state

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"{self.agent_name} failed: {type(e).__name__}: {e}"
            logger.error("[%s] %s", self.agent_name, error_msg)

            state["error"] = error_msg
            state["pipeline_status"] = "failed"
            self._log_audit(
                state,
                action="error",
                reasoning=str(e),
                input_summary="",
                output_summary=f"FAILED: {error_msg}",
                duration_ms=duration_ms,
            )
            return state

    @abstractmethod
    def execute(self, state: AgentState) -> AgentState:
        """
        The agent's actual logic. Implemented by each subclass.
        Receives the current state, returns updated state.
        """
        ...

    def _log_audit(
        self,
        state: AgentState,
        action: str,
        input_summary: str,
        output_summary: str,
        duration_ms: int,
        reasoning: str | None = None,
        input_snapshot: dict | None = None,
        output_snapshot: dict | None = None,
    ) -> None:
        """
        Append an entry to the audit log in state.
        Every significant agent decision should be logged here.
        This is what appears in the UI's "Agent Audit Trail" panel.

        Optional structured snapshots carry richer payloads such
        as the ReAct trace; the API flush stage prefers them when present
        and falls back to the plain summaries otherwise.
        """
        append_audit_entry(
            state,
            agent_name=self.agent_name,
            action=action,
            input_summary=input_summary,
            output_summary=output_summary,
            duration_ms=duration_ms,
            reasoning=reasoning,
            input_snapshot=input_snapshot,
            output_snapshot=output_snapshot,
        )

    def _fetch_suppliers(self, supplier_ids: list[str]) -> list[dict]:
        """Fetch supplier data using sync DB session (no async conflicts)."""
        from app.db.repositories.supplier_repo import (
            SupplierRepository,
            supplier_to_dict,
        )
        from app.db.session import SyncSessionLocal

        with SyncSessionLocal() as db:
            suppliers = SupplierRepository.get_by_ids_sync(db, supplier_ids)
            out = []
            for s in suppliers:
                d = supplier_to_dict(s, clean=True)
                d.update({
                    "description": clean_optional_text(s.description),
                    "category": clean_optional_text(s.category),
                    "certification_details": s.certification_details or {},
                    "source_citations": s.source_citations or {},
                    "website": clean_optional_text(s.website),
                    "contact_email": clean_optional_text(s.contact_email),
                })
                out.append(d)
            return out

    def _extract_country_from_constraints(self, constraints: Mapping[str, Any]) -> str | None:
        if constraints.get("location_country"):
            return constraints["location_country"]
        location = constraints.get("location_name", "") or ""
        if "," in location:
            parts = [p.strip() for p in location.split(",")]
            if len(parts) >= 2:
                return parts[-1]
        return None

    def _extract_city_from_constraints(self, constraints: dict) -> str | None:
        if constraints.get("location_city"):
            return constraints["location_city"]
        location = constraints.get("location_name", "") or ""
        if "," in location:
            parts = [p.strip() for p in location.split(",")]
            return parts[0] if parts else None
        return location if location else None
