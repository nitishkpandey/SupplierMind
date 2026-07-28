"""Verify clarification, resume, persistence, and audit behavior through the live API."""

from __future__ import annotations

import json
import os
import sys
import uuid
from collections.abc import Iterable
from typing import Any

import httpx

DEFAULT_API_URL = "http://127.0.0.1:8000/api/v1"
COUNTRY = "Germany"
QUERY = (
    "i want to buy 1000 (.5l) bottles of helles and Pilsner beer in Germany "
    "for the client who is going to organise the summer party."
)
TERMINAL_EVENTS = frozenset({"complete", "error"})


def parse_sse_events(lines: Iterable[str]) -> list[tuple[str, dict[str, Any]]]:
    """Parse an SSE line stream into JSON event payloads."""
    events: list[tuple[str, dict[str, Any]]] = []
    event_name = "message"
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal event_name, data_lines
        if not data_lines:
            event_name = "message"
            return
        raw_data = "\n".join(data_lines)
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"SSE event {event_name!r} did not contain valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(f"SSE event {event_name!r} payload must be a JSON object")
        events.append((event_name, payload))
        event_name = "message"
        data_lines = []

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            flush()
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event_name = line.removeprefix("event:").strip() or "message"
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").lstrip())
    flush()
    return events


def require_event(
    events: list[tuple[str, dict[str, Any]]],
    event_name: str,
) -> dict[str, Any]:
    """Return the requested event or explain which events were observed."""
    for observed_name, payload in events:
        if observed_name == event_name:
            return payload
    observed = ", ".join(name for name, _ in events) or "none"
    raise AssertionError(
        f"Expected SSE event {event_name!r}; observed events: {observed}"
    )


def assert_clarification_question(payload: dict[str, Any], country: str) -> None:
    """Require a usable city/region versus nationwide clarification question."""
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        raise AssertionError("Clarification event did not include a question")
    normalized = question.casefold()
    if country.casefold() not in normalized:
        raise AssertionError(f"Clarification question did not name {country}: {question!r}")
    if "city" not in normalized and "region" not in normalized:
        raise AssertionError(
            f"Clarification question did not offer a city or region scope: {question!r}"
        )


def assert_terminal_completion(
    events: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Require a successful terminal event and surface pipeline errors clearly."""
    for event_name, payload in events:
        if event_name == "error":
            message = payload.get("message") or "unknown pipeline error"
            raise AssertionError(f"Pipeline error: {message}")
        if event_name == "complete":
            return payload
    observed = ", ".join(name for name, _ in events) or "none"
    raise AssertionError(f"No terminal SSE event was received; observed: {observed}")


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _development_token(
    client: httpx.Client,
    api_url: str,
    scenario: str,
) -> str:
    unique = uuid.uuid4().hex
    response = client.post(
        f"{api_url}/auth/dev-login",
        json={
            "email": f"live.verify.{scenario}.{unique}@suppliermind.local",
            "role": "procurement_manager",
        },
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise AssertionError("Development login did not return an access token")
    return token


def _submit_query(client: httpx.Client, api_url: str, token: str) -> str:
    response = client.post(
        f"{api_url}/queries",
        headers=_auth_headers(token),
        json={"raw_query": QUERY, "search_scope": "both"},
    )
    response.raise_for_status()
    query_id = response.json().get("id")
    if not isinstance(query_id, str) or not query_id:
        raise AssertionError("Query submission did not return a query ID")
    return query_id


def _stream_query(
    client: httpx.Client,
    api_url: str,
    token: str,
    query_id: str,
) -> list[tuple[str, dict[str, Any]]]:
    with client.stream(
        "GET",
        f"{api_url}/queries/{query_id}/stream",
        params={"token": token},
    ) as response:
        response.raise_for_status()
        return parse_sse_events(response.iter_lines())


def _assert_persisted_run(
    client: httpx.Client,
    api_url: str,
    token: str,
    query_id: str,
) -> int:
    headers = _auth_headers(token)
    result_response = client.get(f"{api_url}/queries/{query_id}", headers=headers)
    result_response.raise_for_status()
    result = result_response.json()
    if result.get("status") != "completed":
        raise AssertionError(
            f"Persisted query {query_id} ended with status {result.get('status')!r}: "
            f"{result.get('error_message') or 'no error message'}"
        )
    suppliers = result.get("results")
    if not isinstance(suppliers, list) or not suppliers:
        diagnostics = result.get("diagnostics") or {}
        raise AssertionError(
            "Live discovery completed without a supplier result: "
            f"{diagnostics.get('code') or 'no diagnostic code'}"
        )

    audit_response = client.get(
        f"{api_url}/queries/{query_id}/audit",
        headers=headers,
    )
    audit_response.raise_for_status()
    audit_entries = audit_response.json().get("audit_entries")
    if not isinstance(audit_entries, list) or not audit_entries:
        raise AssertionError(f"Query {query_id} did not persist an agent audit trail")
    agent_names = {
        entry.get("agent_name")
        for entry in audit_entries
        if isinstance(entry, dict)
    }
    required_agents = {"parser", "discovery", "compliance", "ranking"}
    missing_agents = required_agents - agent_names
    if missing_agents:
        missing = ", ".join(sorted(missing_agents))
        raise AssertionError(f"Persisted audit trail is missing agents: {missing}")
    return len(suppliers)


def _run_scenario(
    client: httpx.Client,
    api_url: str,
    *,
    scenario: str,
    answer: str,
) -> int:
    token = _development_token(client, api_url, scenario)
    query_id = _submit_query(client, api_url, token)

    clarification_events = _stream_query(client, api_url, token, query_id)
    clarification = require_event(clarification_events, "needs_clarification")
    assert_clarification_question(clarification, COUNTRY)

    response = client.post(
        f"{api_url}/queries/{query_id}/clarify",
        headers=_auth_headers(token),
        json={"answer": answer},
    )
    response.raise_for_status()
    if response.json().get("status") != "resuming":
        raise AssertionError(f"Clarification for {query_id} did not enter resuming state")

    resumed_events = _stream_query(client, api_url, token, query_id)
    terminal = assert_terminal_completion(resumed_events)
    if terminal.get("query_id") != query_id:
        raise AssertionError("Terminal event did not belong to the submitted query")
    return _assert_persisted_run(client, api_url, token, query_id)


def main() -> int:
    api_url = os.getenv("SUPPLIERMIND_API_URL", DEFAULT_API_URL).rstrip("/")
    timeout = httpx.Timeout(connect=10.0, read=240.0, write=30.0, pool=10.0)

    try:
        with httpx.Client(timeout=timeout) as client:
            city_results = _run_scenario(
                client,
                api_url,
                scenario="city",
                answer="Munich",
            )
            nationwide_results = _run_scenario(
                client,
                api_url,
                scenario="nationwide",
                answer="all of Germany",
            )
    except (httpx.HTTPError, AssertionError, ValueError) as exc:
        print(f"Live discovery verification failed: {exc}", file=sys.stderr)
        return 1

    print(
        "Live discovery verification passed: "
        f"Munich={city_results} supplier(s), "
        f"Germany-wide={nationwide_results} supplier(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
