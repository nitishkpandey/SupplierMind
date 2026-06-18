"""Unit tests for the ReAct Parser loop (Task 3.1 / Component C).

These tests pin the *structure* of the loop, not LLM phrasing. The LLM is
injected as a FakeLLM whose `complete()` returns scripted Thought / Action /
Action Input strings; tools are injected as fakes where they touch the
network. All five tests cover the scenarios in Task 3.1's spec:

1. Simple query, single tool call -> Finish in 2 iterations
2. Multi-tool reasoning             -> 4 iterations across distinct tools
3. Tool failure recovery            -> exception surfaced as Observation
4. Same-args dedup                  -> 2nd identical call refused
5. Max-iteration termination        -> fallback extraction runs
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from app.agents.parser_agent import MAX_REACT_ITERATIONS, ParserAgent
from app.agents.tools import Tool, ToolRegistry
from app.agents.tools.cert_taxonomy import canonicalize_certification_tool
from app.agents.tools.geocode import geocode_location_tool
from app.agents.tools.industry_context import infer_industry_context_tool
from app.agents.tools.past_query_stub import lookup_past_query_tool
from app.agents.tools.quantity_parser import parse_quantity_unit_tool


# ── Fakes ────────────────────────────────────────────────────────────


class _FakeLLM:
    """Scripted LLM: hands out the next response from a list per `complete`.

    If the script is exhausted the LLM falls back to a default refusal response
    that lets the loop continue (used by the max-iterations test where we want
    the loop to spin without ever emitting Finish).
    """

    def __init__(self, responses: list[str], default: str | None = None):
        self.responses = list(responses)
        self.default = default
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages, **kwargs):
        self.calls.append(messages)
        if self.responses:
            return self.responses.pop(0)
        if self.default is not None:
            return self.default
        raise AssertionError("FakeLLM script exhausted and no default set")


class _FakeJSONLLM:
    """Fake for tools that call complete_json (e.g. infer_industry_context)."""

    def __init__(self, payloads: list[str]):
        self.payloads = list(payloads)
        self.calls: list[list[dict[str, str]]] = []

    def complete_json(self, messages, **kwargs):
        self.calls.append(messages)
        return self.payloads.pop(0)


class _FakeGeocoder:
    def __init__(self, result):
        self.result = result
        self.calls: list[str] = []

    def geocode(self, name):
        self.calls.append(name)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _build_registry(geocoder=None, industry_llm=None) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(geocode_location_tool(_geocoder=geocoder))
    reg.register(canonicalize_certification_tool())
    reg.register(infer_industry_context_tool(_llm=industry_llm))
    reg.register(parse_quantity_unit_tool())
    reg.register(lookup_past_query_tool())
    return reg


def _make_state(raw_query: str) -> dict[str, Any]:
    return {
        "raw_query": raw_query,
        "query_id": "q-test",
        "user_id": "",   # skips memory loading
        "audit_log": [],
        "search_scope": "approved_only",
    }


def _make_parser(llm: _FakeLLM, registry: ToolRegistry) -> ParserAgent:
    parser = ParserAgent(tool_registry=registry)
    parser.llm = llm  # type: ignore[assignment]
    return parser


# ── 1. Simple query — single tool call ───────────────────────────────


def test_simple_query_single_tool_then_finish():
    geocoder = _FakeGeocoder((52.52, 13.405))
    registry = _build_registry(geocoder=geocoder)

    finish_payload = {
        "product_type": "packaging",
        "product_keywords": ["packaging", "boxes", "containers"],
        "industry_context": None,
        "buyer_intent": "manufacturer",
        "category_hint": "packaging",
        "location_city": None,
        "location_country": "Germany",
        "location_region": None,
        "location_radius_km": None,
        "certifications": ["ISO 9001"],
        "capacity_min": None,
        "capacity_unit": None,
        "lead_time_max_days": None,
        "query_type": "compliance_critical",
        "complexity": "simple",
        "original_language": "en",
        "confidence": 0.9,
        "clarification_needed": False,
        "clarification_question": None,
    }
    llm = _FakeLLM([
        'Thought: I need coordinates for Germany.\nAction: geocode_location\nAction Input: {"location_name": "Germany"}',
        f'Thought: I have enough information.\nAction: Finish\nAction Input: {json.dumps(finish_payload)}',
    ])
    parser = _make_parser(llm, registry)

    out = parser.execute(_make_state("ISO 9001 packaging supplier in Germany"))

    trace = out["react_trace"]
    assert [s["action"] for s in trace] == ["geocode_location", "Finish"]
    assert out["react_terminated_by"] == "finish"
    constraints = out["parsed_constraints"]
    assert constraints["location_country"] == "Germany"
    assert constraints["location_lat"] == 52.52
    assert constraints["location_lng"] == 13.405
    assert "ISO 9001" in constraints["certifications"]


# ── 2. Multi-tool reasoning ──────────────────────────────────────────


def test_multi_tool_reasoning_chains_distinct_tools():
    geocoder = _FakeGeocoder((48.137, 11.575))
    industry_llm = _FakeJSONLLM([
        '{"industry":"aerospace","common_certs":["AS9100","NADCAP"],"typical_units":"units/month"}',
    ])
    registry = _build_registry(geocoder=geocoder, industry_llm=industry_llm)

    finish_payload = {
        "product_type": "aerospace machining",
        "product_keywords": ["aerospace", "machined parts", "CNC", "precision"],
        "industry_context": "aerospace",
        "buyer_intent": "manufacturer",
        "category_hint": "machinery",
        "location_city": "Bavaria",
        "location_country": None,
        "location_region": None,
        "location_radius_km": None,
        "certifications": ["AS9100"],
        "capacity_min": 10000,
        "capacity_unit": "units/month",
        "lead_time_max_days": None,
        "query_type": "capability_match",
        "complexity": "complex",
        "original_language": "en",
        "confidence": 0.85,
        "clarification_needed": False,
        "clarification_question": None,
    }
    llm = _FakeLLM([
        'Thought: I should geocode Bavaria first.\nAction: geocode_location\nAction Input: {"location_name": "Bavaria"}',
        'Thought: Infer the aerospace industry context.\nAction: infer_industry_context\nAction Input: {"product_description": "aerospace machining"}',
        'Thought: Normalise the cert name.\nAction: canonicalize_certification\nAction Input: {"cert_name": "AS9100"}',
        'Thought: Parse the quantity phrase.\nAction: parse_quantity_unit\nAction Input: {"text": "10k units/month"}',
        f'Thought: Done.\nAction: Finish\nAction Input: {json.dumps(finish_payload)}',
    ])
    parser = _make_parser(llm, registry)

    out = parser.execute(_make_state("AS9100 aerospace machining 10k units/month Bavaria"))

    actions = [s["action"] for s in out["react_trace"]]
    assert actions == [
        "geocode_location",
        "infer_industry_context",
        "canonicalize_certification",
        "parse_quantity_unit",
        "Finish",
    ]
    assert out["react_terminated_by"] == "finish"
    constraints = out["parsed_constraints"]
    assert constraints["capacity_min"] == 10000
    assert constraints["capacity_unit"] == "units/month"
    # AS9100 was named in the query → stays a HARD cert.
    assert "AS9100" in constraints["certifications"]
    # NADCAP only ever came back from infer_industry_context.common_certs, so
    # the provenance guard routes it to the SOFT list and keeps it OUT of the
    # hard gate (previously this correct behaviour was only accidental).
    assert "NADCAP" in constraints["industry_typical_certs"]
    assert "NADCAP" not in constraints["certifications"]


# ── 3. Tool failure recovery ─────────────────────────────────────────


def test_tool_failure_surfaces_as_observation_and_loop_continues():
    geocoder = _FakeGeocoder(RuntimeError("nominatim timeout"))
    registry = _build_registry(geocoder=geocoder)

    finish_payload = {
        "product_type": "packaging",
        "product_keywords": ["packaging"],
        "industry_context": None,
        "buyer_intent": "any",
        "category_hint": "packaging",
        "location_city": None,
        "location_country": "Germany",
        "location_region": None,
        "location_radius_km": None,
        "certifications": ["ISO 9001"],
        "capacity_min": None,
        "capacity_unit": None,
        "lead_time_max_days": None,
        "query_type": "geographic_priority",
        "complexity": "simple",
        "original_language": "en",
        "confidence": 0.65,
        "clarification_needed": False,
        "clarification_question": None,
    }
    llm = _FakeLLM([
        'Thought: Try to geocode.\nAction: geocode_location\nAction Input: {"location_name": "Germany"}',
        f'Thought: Tool failed, finishing with location name only.\nAction: Finish\nAction Input: {json.dumps(finish_payload)}',
    ])
    parser = _make_parser(llm, registry)

    out = parser.execute(_make_state("ISO 9001 packaging supplier in Germany"))

    trace = out["react_trace"]
    assert trace[0]["action"] == "geocode_location"
    assert trace[0]["observation"]["error"] == "RuntimeError"
    assert "nominatim timeout" in trace[0]["observation"]["detail"]
    assert trace[-1]["action"] == "Finish"
    assert out["react_terminated_by"] == "finish"
    constraints = out["parsed_constraints"]
    assert constraints["location_country"] == "Germany"
    # lat/lng remain absent because the geocode failed.
    assert constraints["location_lat"] is None
    assert constraints["location_lng"] is None


# ── 4. Same-args dedup ───────────────────────────────────────────────


def test_same_args_dedup_intercepts_repeat_call():
    geocoder = _FakeGeocoder((52.52, 13.405))
    registry = _build_registry(geocoder=geocoder)

    finish_payload = {
        "product_type": "packaging",
        "product_keywords": ["packaging"],
        "industry_context": None,
        "buyer_intent": "any",
        "category_hint": "packaging",
        "location_city": None,
        "location_country": "Germany",
        "location_region": None,
        "location_radius_km": None,
        "certifications": [],
        "capacity_min": None,
        "capacity_unit": None,
        "lead_time_max_days": None,
        "query_type": "general",
        "complexity": "simple",
        "original_language": "en",
        "confidence": 0.8,
        "clarification_needed": False,
        "clarification_question": None,
    }
    llm = _FakeLLM([
        'Thought: Geocode Germany.\nAction: geocode_location\nAction Input: {"location_name": "Germany"}',
        'Thought: Try again with same args.\nAction: geocode_location\nAction Input: {"location_name": "Germany"}',
        f'Thought: OK done.\nAction: Finish\nAction Input: {json.dumps(finish_payload)}',
    ])
    parser = _make_parser(llm, registry)

    out = parser.execute(_make_state("packaging supplier in Germany"))

    trace = out["react_trace"]
    assert trace[1]["action"] == "geocode_location"
    assert trace[1]["observation"]["error"] == "duplicate_call"
    # The real geocode tool was called once; the dedup intercepted the second.
    assert len(geocoder.calls) == 1
    assert out["react_terminated_by"] == "finish"


# ── 5. Max-iteration termination + fallback extraction ──────────────


def test_max_iteration_termination_runs_fallback():
    # Failing geocoder: the trace recovers NOTHING concrete, so the fallback
    # must keep its clarification (Task 3.4 added a proceed-with-recovery
    # path for productive traces — pinned separately in
    # test_fallback_proceeds_when_trace_recovered_product_and_constraint).
    geocoder = _FakeGeocoder(RuntimeError("nominatim down"))
    registry = _build_registry(geocoder=geocoder)

    # LLM never emits Finish — every response is the same tool call with
    # different args so dedup doesn't fire and the loop drains to the cap.
    responses = [
        f'Thought: Step {i}.\nAction: geocode_location\nAction Input: {{"location_name": "Place{i}"}}'
        for i in range(MAX_REACT_ITERATIONS + 2)
    ]
    llm = _FakeLLM(responses)
    parser = _make_parser(llm, registry)

    out = parser.execute(_make_state("Bronze supplier near Bremen ISO 9001"))

    assert out["react_terminated_by"] == "max_iterations"
    assert len(out["react_trace"]) == MAX_REACT_ITERATIONS
    # Fallback extraction populated constraints from the trace and the
    # raw-query tokeniser, and flagged needs_clarification.
    constraints = out["parsed_constraints"]
    assert constraints["product_keywords"], "fallback should tokenise raw query"
    assert out["needs_clarification"] is True


# ── Audit-log integration ────────────────────────────────────────────


def test_react_trace_lands_in_audit_log_output_snapshot():
    geocoder = _FakeGeocoder((52.52, 13.405))
    registry = _build_registry(geocoder=geocoder)
    finish_payload = {
        "product_type": "packaging",
        "product_keywords": ["packaging"],
        "industry_context": None,
        "buyer_intent": "any",
        "category_hint": "packaging",
        "location_city": None,
        "location_country": "Germany",
        "location_region": None,
        "location_radius_km": None,
        "certifications": [],
        "capacity_min": None,
        "capacity_unit": None,
        "lead_time_max_days": None,
        "query_type": "general",
        "complexity": "simple",
        "original_language": "en",
        "confidence": 0.9,
        "clarification_needed": False,
        "clarification_question": None,
    }
    llm = _FakeLLM([
        'Thought: geocode.\nAction: geocode_location\nAction Input: {"location_name": "Germany"}',
        f'Thought: done.\nAction: Finish\nAction Input: {json.dumps(finish_payload)}',
    ])
    parser = _make_parser(llm, registry)

    out = parser.execute(_make_state("packaging supplier in Germany"))

    audit = out["audit_log"]
    assert len(audit) == 1
    entry = audit[0]
    assert entry["agent_name"] == "parser"
    assert entry["action"] == "react_loop_completed"
    out_snap = entry["output_snapshot"]
    assert out_snap["terminated_by"] == "finish"
    assert out_snap["tools_called"] == ["geocode_location"]
    assert isinstance(out_snap["trace"], list)
    assert out_snap["trace"][-1]["action"] == "Finish"


# -- Hallucinated-Observation hardening (Task 3.4 smoke regression) ----------
#
# Some models emit the Observation (and follow-up commentary) inside their own
# completion. The Task 3.4 smoke run burned 4 of 6 iterations on "Action Input
# is not valid JSON: Extra data" because the old regex captured everything
# from the first { to the last } in the response. These tests pin the two
# defense layers: truncation at a hallucinated "Observation:" and first-JSON-
# value parsing that ignores trailing junk.


def test_parse_react_response_ignores_hallucinated_observation():
    from app.agents.parser_agent import _parse_react_response

    text = (
        "Thought: I need to infer the industry context for packaging.\n"
        "Action: infer_industry_context\n"
        'Action Input: {"product_description": "packaging"}\n'
        "\n"
        'Observation: {"industry_name": "packaging", "certs": ["ISO 9001:2015"]}'
    )
    step = _parse_react_response(text)
    assert step.action == "infer_industry_context"
    assert step.action_input == {"product_description": "packaging"}


def test_parse_react_response_ignores_trailing_commentary_after_json():
    from app.agents.parser_agent import _parse_react_response

    text = (
        "Thought: canonicalize the certification.\n"
        "Action: canonicalize_certification\n"
        'Action Input: {"cert_name": "ISO certified"}\n'
        "\n"
        "(I will make sure to follow the format correctly this time)"
    )
    step = _parse_react_response(text)
    assert step.action == "canonicalize_certification"
    assert step.action_input == {"cert_name": "ISO certified"}


def test_parse_react_response_still_rejects_truly_broken_json():
    from app.agents.parser_agent import _parse_react_response

    text = (
        "Thought: broken.\n"
        "Action: geocode_location\n"
        'Action Input: {"location_name": "Bavaria"'  # unterminated object
    )
    with pytest.raises(ValueError, match="not valid JSON"):
        _parse_react_response(text)


# -- Task 3.4 loop hygiene: per-tool budget + forced finish + fallback -------


def test_third_call_to_same_tool_is_intercepted_even_with_different_args():
    """Exact-args dedup is dodged by argument variations; the per-tool
    budget (2 executions) must intercept the third call regardless."""
    registry = _build_registry(geocoder=_FakeGeocoder((48.1, 11.5)))

    finish_payload = {"product_type": "packaging", "confidence": 0.8,
                      "clarification_needed": False, "query_type": "general"}
    llm = _FakeLLM([
        'Thought: a.\nAction: infer_industry_context\nAction Input: {"product_description": "packaging one"}',
        'Thought: b.\nAction: infer_industry_context\nAction Input: {"product_description": "packaging two"}',
        'Thought: c.\nAction: infer_industry_context\nAction Input: {"product_description": "packaging three"}',
        f'Thought: ok.\nAction: Finish\nAction Input: {json.dumps(finish_payload)}',
    ])
    parser = _make_parser(llm, registry)
    out = parser.execute(_make_state("packaging suppliers with ISO 9001 in Hamburg"))

    trace = out["react_trace"]
    third = trace[2]
    assert third["action"] == "infer_industry_context"
    assert third["observation"].get("error") == "tool_budget_exhausted"
    assert out["react_terminated_by"] == "finish"


def test_final_iteration_receives_force_finish_instruction():
    """On the last allowed iteration the model must be told that only
    Action: Finish is acceptable."""
    registry = _build_registry(geocoder=_FakeGeocoder((48.1, 11.5)))
    # Default response keeps calling a tool with fresh args each time so the
    # loop spins to the cap (vary via responses list).
    responses = [
        f'Thought: spin {i}.\nAction: geocode_location\nAction Input: {{"location_name": "city {i}"}}'
        for i in range(MAX_REACT_ITERATIONS)
    ]
    llm = _FakeLLM(responses)
    parser = _make_parser(llm, registry)
    parser.execute(_make_state("suppliers of industrial gaskets near Cologne"))

    final_call_messages = llm.calls[-1]
    assert any(
        "FINAL step" in (m.get("content") or "") for m in final_call_messages
    ), "last LLM call must carry the force-finish instruction"


def test_fallback_proceeds_when_trace_recovered_product_and_constraint():
    """Task 3.4: a max-iterations run whose trace holds a real product label
    (infer_industry_context action_input) plus a concrete constraint must
    proceed instead of asking the user again."""
    registry = _build_registry(geocoder=_FakeGeocoder((50.9, 6.9)))
    responses = [
        'Thought: industry.\nAction: infer_industry_context\nAction Input: {"product_description": "stainless steel fasteners"}',
        'Thought: where.\nAction: geocode_location\nAction Input: {"location_name": "Germany"}',
    ] + [
        f'Thought: spin {i}.\nAction: infer_industry_context\nAction Input: {{"product_description": "stainless steel fasteners variant {i}"}}'
        for i in range(MAX_REACT_ITERATIONS)
    ]
    llm = _FakeLLM(responses)
    parser = _make_parser(llm, registry)
    out = parser.execute(_make_state("we need fastener supply for construction in Germany"))

    assert out["react_terminated_by"] == "max_iterations"
    assert out["needs_clarification"] is False
    assert out["parsed_constraints"]["product_type"] == "stainless steel fasteners"
    assert out["parsed_constraints"]["location_country"] == "Germany"


# -- Cert provenance guard (cert-hallucination fix) ---------------------------
#
# infer_industry_context surfaces certs "commonly required" in an industry. The
# LLM used to copy those into `certifications` (a HARD compliance gate), which
# FAILed every supplier that lacked the inferred certs. The provenance guard in
# _normalise_constraints keeps user-stated certs hard, routes inference-tool
# certs to the soft `industry_typical_certs` field, and drops certs that have no
# provenance at all. These tests pin that split end-to-end through execute().


def _infer_then_finish_script(product_description: str, finish_payload: dict) -> list[str]:
    return [
        f'Thought: infer the industry.\nAction: infer_industry_context\n'
        f'Action Input: {{"product_description": "{product_description}"}}',
        f'Thought: done.\nAction: Finish\nAction Input: {json.dumps(finish_payload)}',
    ]


def _electronics_finish_payload(certifications: list[str]) -> dict:
    return {
        "product_type": "electronics",
        "product_keywords": ["electronics"],
        "industry_context": "electronics",
        "buyer_intent": "manufacturer",
        "category_hint": "electronics",
        "location_city": "Frankfurt",
        "location_country": None,
        "location_region": None,
        "location_radius_km": None,
        "certifications": certifications,
        "capacity_min": None,
        "capacity_unit": None,
        "lead_time_max_days": None,
        "query_type": "compliance_critical",
        "complexity": "simple",
        "original_language": "en",
        "confidence": 0.9,
        "clarification_needed": False,
        "clarification_question": None,
    }


def test_user_stated_certs_stay_hard():
    """Query names ISO 9001; the tool also surfaces AS9100. After the parse the
    user-stated cert is a hard requirement and the inferred one is soft."""
    registry = _build_registry(
        geocoder=_FakeGeocoder((50.1, 8.7)),
        industry_llm=_FakeJSONLLM([
            '{"industry":"electronics","common_certs":["ISO 9001","AS9100"],"typical_units":"units/month"}'
        ]),
    )
    payload = _electronics_finish_payload(["ISO 9001", "AS9100"])
    llm = _FakeLLM(_infer_then_finish_script("electronics", payload))
    parser = _make_parser(llm, registry)

    out = parser.execute(_make_state("ISO 9001 electronics suppliers near Frankfurt"))

    c = out["parsed_constraints"]
    assert c["certifications"] == ["ISO 9001"]
    assert c["industry_typical_certs"] == ["AS9100"]


def test_inferred_only_certs_move_to_soft():
    """Query states no certs; every cert the tool surfaces must land in the
    soft list, leaving the hard gate empty (the original bug scenario)."""
    registry = _build_registry(
        geocoder=_FakeGeocoder((50.1, 8.7)),
        industry_llm=_FakeJSONLLM([
            '{"industry":"electronics","common_certs":["ISO 9001","AS9100","IPC-A-610"],"typical_units":"units/month"}'
        ]),
    )
    payload = _electronics_finish_payload(["ISO 9001", "AS9100", "IPC-A-610"])
    llm = _FakeLLM(_infer_then_finish_script("electronics", payload))
    parser = _make_parser(llm, registry)

    out = parser.execute(_make_state("electronics suppliers near Frankfurt"))

    c = out["parsed_constraints"]
    assert c["certifications"] == []
    assert c["industry_typical_certs"] == ["ISO 9001", "AS9100", "IPC-A-610"]


def test_hallucinated_certs_dropped(caplog):
    """A cert in the Finish payload that appears neither in the query nor in any
    tool observation has no provenance — drop it from both lists and warn."""
    registry = _build_registry(
        geocoder=_FakeGeocoder((50.1, 8.7)),
        industry_llm=_FakeJSONLLM([
            '{"industry":"electronics","common_certs":["ISO 9001"],"typical_units":null}'
        ]),
    )
    payload = _electronics_finish_payload(["ISO 9001", "FAKECERT-9999"])
    llm = _FakeLLM(_infer_then_finish_script("electronics", payload))
    parser = _make_parser(llm, registry)

    with caplog.at_level(logging.WARNING, logger="app.agents.parser_agent"):
        out = parser.execute(_make_state("electronics suppliers near Frankfurt"))

    c = out["parsed_constraints"]
    assert "FAKECERT-9999" not in c["certifications"]
    assert "FAKECERT-9999" not in c["industry_typical_certs"]
    # ISO 9001 came only from the inference tool here → soft, not hard.
    assert c["certifications"] == []
    assert "ISO 9001" in c["industry_typical_certs"]
    assert "FAKECERT-9999" in caplog.text


def test_case_insensitive_matching():
    """A lower-cased query mention of a cert still counts as user-stated; the
    cert stays hard and is not duplicated into the soft list."""
    registry = _build_registry(
        geocoder=_FakeGeocoder((50.1, 8.7)),
        industry_llm=_FakeJSONLLM([
            '{"industry":"electronics","common_certs":["ISO 9001"],"typical_units":null}'
        ]),
    )
    payload = _electronics_finish_payload(["ISO 9001"])
    llm = _FakeLLM(_infer_then_finish_script("electronics", payload))
    parser = _make_parser(llm, registry)

    out = parser.execute(_make_state("iso 9001 electronics suppliers near Frankfurt"))

    c = out["parsed_constraints"]
    assert c["certifications"] == ["ISO 9001"]
    assert "ISO 9001" not in c["industry_typical_certs"]
