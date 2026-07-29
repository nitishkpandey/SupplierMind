"""Request-context and policy-boundary tests for AI gateways."""

from decimal import Decimal
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
from app.platform.ai.types import (
    AIOperation,
    AIOutcome,
    AIRequestContext,
    DataClassification,
    ProviderUsage,
)
from app.platform.ai.usage import InMemoryAIUsageRecorder


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
    recorder = InMemoryAIUsageRecorder()
    gateway = AIGateway(transport, _policy(), recorder)

    with pytest.raises(AIDataEgressDenied):
        gateway.complete([{"role": "user", "content": "secret"}])

    transport.complete.assert_not_called()
    measurement = recorder.snapshot()[0]
    assert measurement.outcome is AIOutcome.denied
    assert measurement.input_units == 0
    assert measurement.output_units == 0
    assert measurement.error_code == "classification_not_allowed"


def test_internal_context_delegates_and_resets() -> None:
    transport = MagicMock(
        provider_name="openai",
        model_name="gpt-4o-mini-2024-07-18",
        total_cost_usd=0.0,
    )
    recorder = InMemoryAIUsageRecorder()

    def complete(*_args, **_kwargs):
        callback = transport.set_usage_callback.call_args.args[0]
        callback(
            ProviderUsage(
                provider="openai",
                model="gpt-4o-mini-2024-07-18",
                operation=AIOperation.chat,
                input_units=11,
                output_units=3,
                cost_usd=Decimal("0.00000345"),
                latency_ms=25,
            )
        )
        return "ok"

    transport.complete.side_effect = complete
    gateway = AIGateway(transport, _policy(), recorder)
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
    measurement = recorder.snapshot()[0]
    assert measurement.outcome is AIOutcome.success
    assert measurement.purpose == "agent.parser"
    assert measurement.query_id == "query-1"
    assert measurement.input_units == 11
    assert measurement.output_units == 3
    assert measurement.cost_usd == Decimal("0.00000345")


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
    recorder = InMemoryAIUsageRecorder()
    gateway = EmbeddingGateway(transport, _policy(), recorder)

    with pytest.raises(AIDataEgressDenied):
        gateway.embed_one("contract text", input_type="document")

    transport.embed_batch.assert_not_called()
    measurement = recorder.snapshot()[0]
    assert measurement.outcome is AIOutcome.denied
    assert measurement.operation is AIOperation.embedding


def test_gateway_exposes_read_only_transport_metadata() -> None:
    transport = MagicMock(
        provider_name="openai",
        model_name="gpt-4o-mini-2024-07-18",
        total_cost_usd=1.25,
    )
    gateway = AIGateway(
        transport,
        _policy(),
        InMemoryAIUsageRecorder(),
    )

    assert gateway.transport is transport
    assert gateway.provider_name == "openai"
    assert gateway.model_name == "gpt-4o-mini-2024-07-18"
    assert gateway.total_cost_usd == 1.25


def test_gateway_records_provider_error_without_content() -> None:
    transport = MagicMock(
        provider_name="openai",
        model_name="gpt-4o-mini-2024-07-18",
        total_cost_usd=0.0,
    )
    transport.complete.side_effect = RuntimeError("sensitive provider detail")
    recorder = InMemoryAIUsageRecorder()
    gateway = AIGateway(transport, _policy(), recorder)
    context = AIRequestContext(
        purpose="agent.evaluator",
        classification=DataClassification.internal,
        correlation_id="request-9",
    )

    with (
        ai_request_scope(context),
        pytest.raises(RuntimeError, match="sensitive provider detail"),
    ):
        gateway.complete([{"role": "user", "content": "private prompt"}])

    measurement = recorder.snapshot()[0]
    assert measurement.outcome is AIOutcome.error
    assert measurement.error_code == "RuntimeError"
    assert measurement.input_units == 0
    assert "sensitive provider detail" not in repr(measurement)
    assert "private prompt" not in repr(measurement)


def test_embedding_gateway_copies_safe_request_metadata() -> None:
    transport = MagicMock(
        provider_name="voyage",
        model_name="voyage-3-lite",
    )
    recorder = InMemoryAIUsageRecorder()

    def embed_batch(*_args, **_kwargs):
        callback = transport.set_usage_callback.call_args.args[0]
        callback(
            ProviderUsage(
                provider="voyage",
                model="voyage-3-lite",
                operation=AIOperation.embedding,
                input_units=19,
                output_units=0,
                cost_usd=None,
                latency_ms=14,
            )
        )
        return [[0.0, 1.0]]

    transport.embed_batch.side_effect = embed_batch
    gateway = EmbeddingGateway(transport, _policy(), recorder)
    context = AIRequestContext(
        purpose="ingestion.index",
        classification=DataClassification.internal,
        job_id="33333333-3333-3333-3333-333333333333",
        source_document_id="44444444-4444-4444-4444-444444444444",
        correlation_id="ingestion-4",
        redaction_applied=True,
        excerpted=True,
    )

    with ai_request_scope(context):
        assert gateway.embed_one("supplier document") == [0.0, 1.0]

    measurement = recorder.snapshot()[0]
    assert measurement.outcome is AIOutcome.success
    assert measurement.job_id == context.job_id
    assert measurement.source_document_id == context.source_document_id
    assert measurement.redaction_applied is True
    assert measurement.excerpted is True
    assert measurement.cost_usd is None


def test_gateway_rejects_transport_callback_without_active_call() -> None:
    transport = MagicMock(
        provider_name="openai",
        model_name="gpt-4o-mini-2024-07-18",
        total_cost_usd=0.0,
    )
    AIGateway(transport, _policy(), InMemoryAIUsageRecorder())
    callback = transport.set_usage_callback.call_args.args[0]

    with pytest.raises(RuntimeError, match="outside an active gateway call"):
        callback(
            ProviderUsage(
                provider="openai",
                model="gpt-4o-mini-2024-07-18",
                operation=AIOperation.chat,
                input_units=1,
                output_units=1,
                cost_usd=Decimal("0.000001"),
                latency_ms=1,
            )
        )


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
