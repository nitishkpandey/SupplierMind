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
from datetime import datetime, timezone

from app.agents.state import AgentState, AuditEntry
from app.core.llm import LLMClient, get_llm_client

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
        logger.info("[%s] Starting", self.agent_name)

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
    ) -> None:
        """
        Append an entry to the audit log in state.
        Every significant agent decision should be logged here.
        This is what appears in the UI's "Agent Audit Trail" panel.
        """
        entry: AuditEntry = {
            "agent_name": self.agent_name,
            "action": action,
            "reasoning": reasoning,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "duration_ms": duration_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if "audit_log" not in state or state["audit_log"] is None:
            state["audit_log"] = []
        state["audit_log"].append(entry)
