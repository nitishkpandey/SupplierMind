import pytest


def _verification_api():
    from scripts.verify_live_discovery import (
        assert_clarification_question,
        assert_terminal_completion,
        parse_sse_events,
        require_event,
    )

    return (
        parse_sse_events,
        require_event,
        assert_clarification_question,
        assert_terminal_completion,
    )


def test_parse_sse_events_supports_multiline_json_data():
    parse_sse_events, _, _, _ = _verification_api()

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
    parse_sse_events, _, _, _ = _verification_api()

    events = parse_sse_events([
        ": keepalive",
        "event: needs_clarification",
        'data: {"question": "Which city in France?"}',
    ])

    assert events == [
        ("needs_clarification", {"question": "Which city in France?"}),
    ]


def test_parse_sse_events_reports_invalid_json_with_event_name():
    parse_sse_events, _, _, _ = _verification_api()

    with pytest.raises(ValueError, match="needs_clarification.*valid JSON"):
        parse_sse_events([
            "event: needs_clarification",
            "data: not-json",
            "",
        ])


def test_require_event_reports_observed_event_names():
    _, require_event, _, _ = _verification_api()
    events = [("connected", {"query_id": "query-1"})]

    with pytest.raises(AssertionError, match="needs_clarification.*connected"):
        require_event(events, "needs_clarification")


def test_clarification_question_requires_country_and_scope_choice():
    _, _, assert_clarification_question, _ = _verification_api()

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
    _, _, _, assert_terminal_completion = _verification_api()

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
