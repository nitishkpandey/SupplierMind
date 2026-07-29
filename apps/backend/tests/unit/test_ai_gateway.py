"""Request-context and policy-boundary tests for AI gateways."""

from unittest.mock import MagicMock, patch

import pytest

from app.core import embeddings as embeddings_mod
from app.core.embeddings import EmbeddingClient, get_embedding_client
from app.platform.ai.context import (
    ai_request_scope,
    current_ai_request_context,
    derive_ai_request_context,
)
from app.platform.ai.gateway import AIGateway, EmbeddingGateway
from app.platform.ai.policy import AIDataEgressDenied, AIPolicyEngine
from app.platform.ai.types import AIRequestContext, DataClassification


def _policy() -> AIPolicyEngine:
    externally_allowed = frozenset(
        {DataClassification.public, DataClassification.internal}
    )
    return AIPolicyEngine(
        {
            "openai": externally_allowed,
            "voyage": externally_allowed,
        }
    )


def test_unbound_gateway_call_is_denied_before_transport() -> None:
    transport = MagicMock(
        provider_name="openai",
        model_name="gpt-4o-mini-2024-07-18",
        total_cost_usd=0.0,
    )
    gateway = AIGateway(transport, _policy())

    with pytest.raises(AIDataEgressDenied):
        gateway.complete([{"role": "user", "content": "secret"}])

    transport.complete.assert_not_called()


def test_internal_context_delegates_and_resets() -> None:
    transport = MagicMock(
        provider_name="openai",
        model_name="gpt-4o-mini-2024-07-18",
        total_cost_usd=0.0,
    )
    transport.complete.return_value = "ok"
    gateway = AIGateway(transport, _policy())
    original = current_ai_request_context()
    context = AIRequestContext(
        purpose="agent.parser",
        classification=DataClassification.internal,
        query_id="query-1",
    )

    with ai_request_scope(context):
        assert (
            gateway.complete(
                [{"role": "user", "content": "supplier query"}]
            )
            == "ok"
        )
        assert current_ai_request_context() == context

    assert current_ai_request_context() == original


def test_nested_scope_derives_purpose_and_restores_parent() -> None:
    parent = AIRequestContext(
        purpose="query.pipeline",
        classification=DataClassification.internal,
        query_id="query-1",
    )

    with ai_request_scope(parent):
        child = derive_ai_request_context(purpose="agent.parser")
        with ai_request_scope(child):
            assert current_ai_request_context().purpose == "agent.parser"
            assert current_ai_request_context().query_id == "query-1"
        assert current_ai_request_context() == parent


def test_embedding_gateway_denies_restricted_data() -> None:
    transport = MagicMock(
        provider_name="voyage",
        model_name="voyage-3-lite",
    )
    gateway = EmbeddingGateway(transport, _policy())

    with pytest.raises(AIDataEgressDenied):
        gateway.embed_one("contract text", input_type="document")

    transport.embed_batch.assert_not_called()


def test_gateway_exposes_read_only_transport_metadata() -> None:
    transport = MagicMock(
        provider_name="openai",
        model_name="gpt-4o-mini-2024-07-18",
        total_cost_usd=1.25,
    )
    gateway = AIGateway(transport, _policy())

    assert gateway.transport is transport
    assert gateway.provider_name == "openai"
    assert gateway.model_name == "gpt-4o-mini-2024-07-18"
    assert gateway.total_cost_usd == 1.25


def test_embedding_factory_returns_policy_gateway() -> None:
    get_embedding_client.cache_clear()
    try:
        with (
            patch.object(embeddings_mod.settings, "VOYAGE_API_KEY", "test-key"),
            patch.object(embeddings_mod.voyageai, "Client", MagicMock()),
        ):
            client = get_embedding_client()

        assert isinstance(client, EmbeddingGateway)
        assert isinstance(client.transport, EmbeddingClient)
        assert client.provider_name == "voyage"
    finally:
        get_embedding_client.cache_clear()
