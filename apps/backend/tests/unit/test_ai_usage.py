"""Privacy and persistence tests for AI usage telemetry."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import SQLAlchemyError

from app.core import embeddings as embeddings_mod
from app.core.embeddings import EMBEDDING_DIM, EmbeddingClient
from app.db.models import AIUsageEvent
from app.db.repositories.ai_usage_repo import AIUsageRepository
from app.platform.ai.context import new_query_ai_context
from app.platform.ai.types import (
    AIOperation,
    AIOutcome,
    AIUsageMeasurement,
    DataClassification,
)
from app.platform.ai.usage import (
    DatabaseAIUsageRecorder,
    InMemoryAIUsageRecorder,
)


def _measurement() -> AIUsageMeasurement:
    return AIUsageMeasurement(
        purpose="agent.parser",
        classification=DataClassification.internal,
        operation=AIOperation.chat,
        provider="openai",
        model="gpt-4o-mini-2024-07-18",
        input_units=120,
        output_units=30,
        cost_usd=Decimal("0.000036"),
        latency_ms=240,
        outcome=AIOutcome.success,
        query_id="22222222-2222-2222-2222-222222222222",
        user_id="11111111-1111-1111-1111-111111111111",
        job_id="33333333-3333-3333-3333-333333333333",
        source_document_id="44444444-4444-4444-4444-444444444444",
        correlation_id="request-1",
        redaction_applied=True,
        excerpted=True,
    )


def test_usage_measurement_has_no_content_field() -> None:
    names = set(AIUsageMeasurement.__dataclass_fields__)

    assert names.isdisjoint(
        {"prompt", "messages", "content", "document_text", "response"}
    )


def test_usage_table_has_no_content_column() -> None:
    columns = set(AIUsageEvent.__table__.columns.keys())
    constraints = {
        constraint.name for constraint in AIUsageEvent.__table__.constraints
    }

    assert columns.isdisjoint(
        {"prompt", "messages", "content", "document_text", "response"}
    )
    assert {
        "classification",
        "purpose",
        "provider",
        "model",
        "input_units",
        "output_units",
        "cost_usd",
        "latency_ms",
        "outcome",
    } <= columns
    assert {
        "ai_usage_input_units_nonnegative",
        "ai_usage_output_units_nonnegative",
        "ai_usage_latency_nonnegative",
        "ai_usage_cost_nonnegative",
        "ai_usage_classification_valid",
    } <= constraints


def test_repository_records_safe_fields_and_commits() -> None:
    session = MagicMock()

    AIUsageRepository.record_sync(session, _measurement())

    event = session.add.call_args.args[0]
    assert event.provider == "openai"
    assert event.classification == "internal"
    assert event.cost_usd == Decimal("0.000036")
    assert str(event.query_id) == "22222222-2222-2222-2222-222222222222"
    assert str(event.job_id) == "33333333-3333-3333-3333-333333333333"
    assert event.redaction_applied is True
    assert event.excerpted is True
    session.commit.assert_called_once_with()


def test_known_query_cost_seeds_resumed_query_budget() -> None:
    session = MagicMock()
    session.scalar.return_value = Decimal("0.125")

    known_cost = AIUsageRepository.known_query_cost_sync(
        session,
        "22222222-2222-2222-2222-222222222222",
    )
    context = new_query_ai_context(
        purpose="query.pipeline",
        classification=DataClassification.internal,
        user_id="11111111-1111-1111-1111-111111111111",
        query_id="22222222-2222-2222-2222-222222222222",
        initial_spent_usd=known_cost,
    )

    assert known_cost == Decimal("0.125")
    assert context.budget is not None
    assert context.budget.spent_usd == Decimal("0.125")
    session.scalar.assert_called_once()


def test_unknown_query_costs_are_not_invented_as_zero_cost_events() -> None:
    session = MagicMock()
    session.scalar.return_value = None

    known_cost = AIUsageRepository.known_query_cost_sync(
        session,
        "22222222-2222-2222-2222-222222222222",
    )

    assert known_cost == Decimal("0")


def test_in_memory_recorder_returns_a_copy() -> None:
    recorder = InMemoryAIUsageRecorder()

    recorder.record(_measurement())
    snapshot = recorder.snapshot()
    snapshot.clear()

    assert len(recorder.snapshot()) == 1


def test_database_recorder_logs_only_safe_failure_metadata(caplog) -> None:
    recorder = DatabaseAIUsageRecorder()
    secret_error = "database rejected SECRET-PROMPT-CONTENT"

    with (
        patch(
            "app.platform.ai.usage.SyncSessionLocal",
            return_value=MagicMock(),
        ),
        patch.object(
            AIUsageRepository,
            "record_sync",
            side_effect=SQLAlchemyError(secret_error),
        ),
    ):
        recorder.record(_measurement())

    assert "SECRET-PROMPT-CONTENT" not in caplog.text
    assert "openai" in caplog.text
    assert "request-1" in caplog.text
    assert "SQLAlchemyError" in caplog.text


def test_voyage_provider_emits_usage_for_cache_miss_only() -> None:
    emitted = []
    vector = [0.0] * EMBEDDING_DIM
    fake_client = MagicMock()
    fake_client.embed.return_value = SimpleNamespace(
        embeddings=[vector],
        total_tokens=7,
    )
    embeddings_mod._EMBED_CACHE.clear()

    with (
        patch.object(embeddings_mod.settings, "VOYAGE_API_KEY", "test-key"),
        patch.object(
            embeddings_mod.voyageai,
            "Client",
            return_value=fake_client,
        ),
    ):
        client = EmbeddingClient(usage_callback=emitted.append)
        assert client.embed_one("sensitive supplier text") == vector
        assert client.embed_one("sensitive supplier text") == vector

    assert fake_client.embed.call_count == 1
    assert len(emitted) == 1
    usage = emitted[0]
    assert usage.operation is AIOperation.embedding
    assert usage.input_units == 7
    assert usage.output_units == 0
    assert usage.cost_usd is None
    assert "sensitive supplier text" not in repr(usage)
