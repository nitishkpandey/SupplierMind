"""AI request-context propagation across agents and worker threads."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.agents import orchestrator
from app.agents.base import BaseAgent
from app.platform.ai.budget import AIBudgetExceeded, AIBudgetLedger
from app.platform.ai.context import (
    ai_request_scope,
    current_ai_request_context,
)
from app.platform.ai.gateway import AIGateway
from app.platform.ai.policy import AIPolicyEngine
from app.platform.ai.types import (
    AIRequestContext,
    DataClassification,
)
from app.platform.ai.usage import InMemoryAIUsageRecorder


class ContextProbeAgent(BaseAgent):
    agent_name = "probe"

    def __init__(self) -> None:
        pass

    def execute(self, state):
        context = current_ai_request_context()
        state["observed_ai_context"] = {
            "purpose": context.purpose,
            "classification": context.classification.value,
            "query_id": context.query_id,
            "user_id": context.user_id,
            "budget_id": id(context.budget),
        }
        return state


def _fake_session_factory() -> MagicMock:
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    return session


def test_base_agent_derives_internal_context_from_state() -> None:
    state = {
        "query_id": "22222222-2222-2222-2222-222222222222",
        "user_id": "11111111-1111-1111-1111-111111111111",
    }

    result = ContextProbeAgent().run(state)

    observed = result["observed_ai_context"]
    assert observed["purpose"] == "agent.probe"
    assert observed["classification"] == "internal"
    assert observed["query_id"] == state["query_id"]
    assert observed["user_id"] == state["user_id"]


def test_base_agent_preserves_root_query_budget() -> None:
    ledger = AIBudgetLedger(limit_usd=Decimal("0.50"))
    root = AIRequestContext(
        purpose="query.pipeline",
        classification=DataClassification.internal,
        user_id="11111111-1111-1111-1111-111111111111",
        query_id="22222222-2222-2222-2222-222222222222",
        budget=ledger,
    )

    with ai_request_scope(root):
        result = ContextProbeAgent().run({})

    assert result["observed_ai_context"]["budget_id"] == id(ledger)
    assert result["observed_ai_context"]["purpose"] == "agent.probe"


def test_base_agent_does_not_override_authoritative_root_ids() -> None:
    root = AIRequestContext(
        purpose="evaluation.pipeline",
        classification=DataClassification.internal,
        user_id=None,
        query_id=None,
    )

    with ai_request_scope(root):
        result = ContextProbeAgent().run(
            {
                "user_id": "non-persistent-user",
                "query_id": "non-persistent-query",
            }
        )

    assert result["observed_ai_context"]["user_id"] is None
    assert result["observed_ai_context"]["query_id"] is None


@pytest.mark.asyncio
async def test_pipeline_worker_receives_root_context(
    monkeypatch,
) -> None:
    class ProbePipeline:
        def invoke(self, state):
            context = current_ai_request_context()
            state["observed_ai_context"] = {
                "purpose": context.purpose,
                "classification": context.classification.value,
                "query_id": context.query_id,
                "user_id": context.user_id,
                "spent_usd": context.budget.spent_usd,
            }
            return state

    monkeypatch.setattr(orchestrator, "get_pipeline", lambda: ProbePipeline())
    monkeypatch.setattr(
        orchestrator,
        "SyncSessionLocal",
        _fake_session_factory,
    )
    monkeypatch.setattr(
        orchestrator.AIUsageRepository,
        "known_query_cost_sync",
        lambda _db, _query_id: Decimal("0.125"),
    )

    result = await orchestrator.run_pipeline(
        raw_query="Find audited metal suppliers in Germany",
        query_id="22222222-2222-2222-2222-222222222222",
        user_id="11111111-1111-1111-1111-111111111111",
    )

    observed = result["observed_ai_context"]
    assert observed["purpose"] == "query.pipeline"
    assert observed["classification"] == "internal"
    assert observed["query_id"] == result["query_id"]
    assert observed["user_id"] == result["user_id"]
    assert observed["spent_usd"] == Decimal("0.125")


@pytest.mark.asyncio
async def test_known_spend_limits_resumed_query_budget(
    monkeypatch,
) -> None:
    transport = MagicMock(
        provider_name="openai",
        model_name="gpt-4o-mini-2024-07-18",
        total_cost_usd=0.0,
    )
    policy = AIPolicyEngine(
        {"openai": frozenset({DataClassification.internal})}
    )
    gateway = AIGateway(
        transport,
        policy,
        InMemoryAIUsageRecorder(),
    )

    class BudgetProbePipeline:
        def invoke(self, state):
            with pytest.raises(AIBudgetExceeded):
                gateway.complete(
                    [{"role": "user", "content": "supplier query"}],
                    max_tokens=5,
                )
            state["budget_denied"] = True
            return state

    monkeypatch.setattr(
        orchestrator,
        "get_pipeline",
        lambda: BudgetProbePipeline(),
    )
    monkeypatch.setattr(
        orchestrator,
        "SyncSessionLocal",
        _fake_session_factory,
    )
    monkeypatch.setattr(
        orchestrator.AIUsageRepository,
        "known_query_cost_sync",
        lambda _db, _query_id: Decimal("0.50"),
    )

    result = await orchestrator.run_pipeline(
        raw_query="Find audited metal suppliers in Germany",
        query_id="22222222-2222-2222-2222-222222222222",
        user_id="11111111-1111-1111-1111-111111111111",
        turn_number=2,
    )

    assert result["budget_denied"] is True
    transport.complete.assert_not_called()
