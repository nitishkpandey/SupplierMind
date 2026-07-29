import logging
from decimal import Decimal

import pytest


def _verification_api():
    from scripts.verify_live_discovery import (
        GENERIC_SCENARIOS,
        assert_clarification_question,
        assert_persisted_payload,
        assert_terminal_completion,
        parse_sse_events,
        require_event,
    )

    return (
        parse_sse_events,
        require_event,
        assert_clarification_question,
        assert_terminal_completion,
        assert_persisted_payload,
        GENERIC_SCENARIOS,
    )


def test_parse_sse_events_supports_multiline_json_data():
    parse_sse_events, *_ = _verification_api()

    events = parse_sse_events([
        "event: agent_update",
        'data: {"agent": "parser",',
        'data: "status": "completed"}',
        "",
        "event: complete",
        'data: {"query_id": "query-1", "status": "completed"}',
        "",
    ])

    assert events == [
        ("agent_update", {"agent": "parser", "status": "completed"}),
        ("complete", {"query_id": "query-1", "status": "completed"}),
    ]


def test_parse_sse_events_flushes_final_event_without_blank_line():
    parse_sse_events, *_ = _verification_api()

    events = parse_sse_events([
        ": keepalive",
        "event: needs_clarification",
        'data: {"question": "Which city in France?"}',
    ])

    assert events == [
        ("needs_clarification", {"question": "Which city in France?"}),
    ]


def test_parse_sse_events_reports_invalid_json_with_event_name():
    parse_sse_events, *_ = _verification_api()

    with pytest.raises(ValueError, match="needs_clarification.*valid JSON"):
        parse_sse_events([
            "event: needs_clarification",
            "data: not-json",
            "",
        ])


def test_require_event_reports_observed_event_names():
    _, require_event, *_ = _verification_api()
    events = [("connected", {"query_id": "query-1"})]

    with pytest.raises(AssertionError, match="needs_clarification.*connected"):
        require_event(events, "needs_clarification")


def test_clarification_question_requires_country_and_scope_choice():
    _, _, assert_clarification_question, *_ = _verification_api()

    assert_clarification_question(
        {
            "question": (
                "Which city or region should I search near, "
                "or should I search all of Germany?"
            )
        },
        "Germany",
    )

    with pytest.raises(AssertionError, match="Germany"):
        assert_clarification_question(
            {"question": "Which city or region should I search near?"},
            "Germany",
        )

    with pytest.raises(AssertionError, match="city or region"):
        assert_clarification_question(
            {"question": "Should I search all of Germany?"},
            "Germany",
        )


def test_terminal_completion_rejects_errors_and_non_terminal_streams():
    _, _, _, assert_terminal_completion, _, _ = _verification_api()

    payload = assert_terminal_completion([
        ("agent_update", {"agent": "ranking"}),
        ("complete", {"query_id": "query-1", "status": "completed"}),
    ])
    assert payload["query_id"] == "query-1"

    with pytest.raises(AssertionError, match="Pipeline error: dependency unavailable"):
        assert_terminal_completion([
            ("error", {"message": "dependency unavailable"}),
        ])

    with pytest.raises(AssertionError, match="No terminal SSE event"):
        assert_terminal_completion([
            ("connected", {"query_id": "query-1"}),
        ])


def test_generic_scenarios_cover_different_products_constraints_and_scopes():
    *_, generic_scenarios = _verification_api()

    assert len(generic_scenarios) == 4
    queries = [scenario.query.casefold() for scenario in generic_scenarios]
    assert any("office furniture" in query and "iso 9001" in query for query in queries)
    assert any("recyclable" in query and "within 30 days" in query for query in queries)
    assert any("aerospace" in query and "as9100" in query for query in queries)
    assert any("textile" in query and "france" in query for query in queries)
    assert sum(scenario.clarification_answer is not None for scenario in generic_scenarios) == 2


def test_persisted_payload_allows_valid_zero_match_generic_run():
    *_, assert_persisted_payload, _ = _verification_api()
    result = {
        "status": "completed",
        "results": [],
        "diagnostics": {"code": "strict_constraints_no_match"},
    }
    audit = {
        "audit_entries": [
            {"agent_name": agent}
            for agent in ("parser", "discovery", "compliance", "ranking")
        ]
    }

    assert assert_persisted_payload(
        result,
        audit,
        query_id="query-1",
        require_results=False,
    ) == 0

    with pytest.raises(AssertionError, match="without a supplier result"):
        assert_persisted_payload(
            result,
            audit,
            query_id="query-1",
            require_results=True,
        )


def test_persisted_payload_requires_complete_audit_chain():
    *_, assert_persisted_payload, _ = _verification_api()
    result = {"status": "completed", "results": [{"supplier_id": "supplier-1"}]}
    audit = {
        "audit_entries": [
            {"agent_name": "parser"},
            {"agent_name": "discovery"},
        ]
    }

    with pytest.raises(AssertionError, match="compliance, ranking"):
        assert_persisted_payload(
            result,
            audit,
            query_id="query-1",
            require_results=False,
        )


def test_provider_check_persists_only_safe_gateway_usage(
    monkeypatch,
    caplog,
) -> None:
    from app.core import llm as llm_module
    from app.core.llm import OpenAIProvider
    from app.platform.ai.context import current_ai_request_context
    from app.platform.ai.gateway import AIGateway
    from app.platform.ai.policy import AIPolicyEngine
    from app.platform.ai.types import (
        AIOperation,
        AIOutcome,
        DataClassification,
        ProviderUsage,
    )
    from app.platform.ai.usage import InMemoryAIUsageRecorder
    from scripts import provider_integration_check

    class FakeOpenAITransport(OpenAIProvider):
        provider_name = "openai"
        model_name = "gpt-4o-mini-2024-07-18"
        total_cost_usd = 0.00000105

        def __init__(self) -> None:
            self.contexts = []
            self._usage_callback = None

        def set_usage_callback(self, callback) -> None:
            self._usage_callback = callback

        def complete(self, _messages, **_kwargs):
            self.contexts.append(current_ai_request_context())
            self._usage_callback(
                ProviderUsage(
                    provider=self.provider_name,
                    model=self.model_name,
                    operation=AIOperation.chat,
                    input_units=3,
                    output_units=1,
                    cost_usd=Decimal("0.00000105"),
                    latency_ms=2,
                )
            )
            return "provider-ok"

    transport = FakeOpenAITransport()
    recorder = InMemoryAIUsageRecorder()
    gateway = AIGateway(
        transport,
        AIPolicyEngine(
            {
                "openai": frozenset(
                    {
                        DataClassification.public,
                        DataClassification.internal,
                    }
                )
            }
        ),
        recorder,
    )
    observed_correlation_ids = []

    def find_usage_event(correlation_id):
        observed_correlation_ids.append(correlation_id)
        return next(
            (
                event
                for event in recorder.snapshot()
                if event.correlation_id == correlation_id
            ),
            None,
        )

    monkeypatch.setattr(llm_module, "get_llm_client", lambda: gateway)
    monkeypatch.setattr(
        provider_integration_check,
        "_find_usage_event",
        find_usage_event,
        raising=False,
    )
    caplog.set_level(logging.INFO)

    provider_integration_check.check_provider()

    assert isinstance(gateway, AIGateway)
    assert isinstance(gateway.transport, OpenAIProvider)
    assert len(recorder.snapshot()) == 1
    event = recorder.snapshot()[0]
    assert event.purpose == "provider.smoke_check"
    assert event.classification is DataClassification.public
    assert event.outcome is AIOutcome.success
    assert "provider-ok" not in repr(event)
    assert observed_correlation_ids == [event.correlation_id]
    assert "provider-ok" not in caplog.text
    assert "provider=openai" in caplog.text
    assert "model=gpt-4o-mini-2024-07-18" in caplog.text
    assert "cost_usd=0.00000105" in caplog.text
