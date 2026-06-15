"""Unit tests for the Parser's Task 3.3 clarification trigger.

These tests pin the decision logic of `_decide_clarification`: when does the
Parser ask a user question after the ReAct loop finishes, and when does it
proceed to downstream agents. The clarification-question-composer LLM call
is scripted via FakeLLM so we control exactly what comes back.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.agents.parser_agent import (
    CLARIFICATION_CONFIDENCE_FLOOR,
    ParserAgent,
)
from app.agents.tools import Tool, ToolRegistry
from app.agents.tools.cert_taxonomy import canonicalize_certification_tool
from app.agents.tools.geocode import geocode_location_tool
from app.agents.tools.industry_context import infer_industry_context_tool
from app.agents.tools.past_query_stub import lookup_past_query_tool
from app.agents.tools.quantity_parser import parse_quantity_unit_tool


# ── Fakes ────────────────────────────────────────────────────────────


class _FakeLLM:
    """Scripted LLM identical to the one in test_parser_react.

    Each call to `complete()` pops the next response from the script.
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


class _FakeGeocoder:
    def __init__(self, result):
        self.result = result
        self.calls: list[str] = []

    def geocode(self, name):
        self.calls.append(name)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _build_registry(geocoder=None, lookup_fn=None) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(geocode_location_tool(_geocoder=geocoder))
    reg.register(canonicalize_certification_tool())
    reg.register(infer_industry_context_tool())
    reg.register(parse_quantity_unit_tool())
    if lookup_fn is None:
        reg.register(lookup_past_query_tool())
    else:
        # Override the stub with a fake that returns the supplied memory rows.
        from app.agents.tools.past_query_stub import _DESCRIPTION, _ARGS_SCHEMA
        reg.register(
            Tool(
                name="lookup_past_query",
                description=_DESCRIPTION,
                args_schema=_ARGS_SCHEMA,
                fn=lookup_fn,
            )
        )
    return reg


def _make_state(raw_query: str) -> dict[str, Any]:
    return {
        "raw_query": raw_query,
        "query_id": "q-test",
        "user_id": "",  # skip memory loading
        "audit_log": [],
        "search_scope": "approved_only",
    }


def _make_parser(llm: _FakeLLM, registry: ToolRegistry) -> ParserAgent:
    parser = ParserAgent(tool_registry=registry)
    parser.llm = llm  # type: ignore[assignment]
    return parser


# ── 1. Clear query → no clarification ────────────────────────────────


def test_clear_query_does_not_trigger_clarification():
    """A fully-specified query (product + cert + country) with high confidence
    should NEVER raise a clarification — the Parser proceeds normally."""
    geocoder = _FakeGeocoder((52.52, 13.405))
    registry = _build_registry(geocoder=geocoder)

    finish_payload = {
        "product_type": "cardboard packaging",
        "product_keywords": ["cardboard", "boxes", "packaging"],
        "industry_context": "packaging",
        "buyer_intent": "manufacturer",
        "category_hint": "packaging",
        "location_city": None,
        "location_country": "Germany",
        "location_region": None,
        "location_radius_km": None,
        "certifications": ["ISO 9001"],
        "capacity_min": 10000,
        "capacity_unit": "units/month",
        "lead_time_max_days": None,
        "query_type": "compliance_critical",
        "complexity": "simple",
        "original_language": "en",
        "confidence": 0.9,
        "clarification_needed": False,
        "clarification_question": None,
    }
    llm = _FakeLLM([
        'Thought: Geocode Germany.\nAction: geocode_location\nAction Input: {"location_name": "Germany"}',
        f'Thought: Done.\nAction: Finish\nAction Input: {json.dumps(finish_payload)}',
    ])
    parser = _make_parser(llm, registry)

    out = parser.execute(_make_state(
        "ISO 9001 cardboard packaging supplier in Germany, 10000 units/month"
    ))

    assert out["needs_clarification"] is False
    assert out["clarification_question"] is None
    assert out["pipeline_status"] == "running"
    # No clarification audit entry should have been appended.
    clarification_entries = [
        e for e in out["audit_log"]
        if e.get("agent_name") == "clarification_handler"
    ]
    assert clarification_entries == []


# ── 2. Ambiguous query (no product) → clarification raised ───────────


def test_missing_product_triggers_clarification_rule_1():
    """Rule 1: no product_type extracted AND lookup_past_query was either
    not called or returned empty → the Parser composes a question that
    targets the missing product."""
    geocoder = _FakeGeocoder((0.0, 0.0))
    registry = _build_registry(geocoder=geocoder)

    finish_payload = {
        "product_type": None,
        "product_keywords": ["suppliers"],
        "industry_context": None,
        "buyer_intent": "any",
        "category_hint": None,
        "location_city": None,
        "location_country": None,
        "location_region": None,
        "location_radius_km": None,
        "certifications": [],
        "capacity_min": None,
        "capacity_unit": None,
        "lead_time_max_days": None,
        "query_type": "general",
        "complexity": "simple",
        "original_language": "en",
        "confidence": 0.55,  # high enough not to trip Rule 2 alone
        "clarification_needed": False,
        "clarification_question": None,
    }
    llm = _FakeLLM([
        # Iter 0: try memory lookup — comes back empty (the stub default).
        'Thought: Check past queries first.\nAction: lookup_past_query\nAction Input: {"query_text": "suppliers for the Helios initiative", "top_k": 3}',
        # Iter 1: nothing useful, finish with sparse constraints.
        f'Thought: No prior context, finishing thin.\nAction: Finish\nAction Input: {json.dumps(finish_payload)}',
        # Iter 2: this is the clarification-composer call.
        "What product are you sourcing? For example: packaging, electronics, or raw materials.",
    ])
    parser = _make_parser(llm, registry)

    # Content-bearing tokens ("Helios initiative") keep the Task 3.4
    # pre-loop gate quiet — this test pins the IN-LOOP Rule 1 trigger.
    # The truly contentless variant lives in
    # test_contentless_query_raises_clarification_without_react_loop.
    out = parser.execute(_make_state("find me suppliers for the Helios initiative"))

    assert out["needs_clarification"] is True
    assert out["pipeline_status"] == "needs_clarification"
    q = out["clarification_question"]
    assert q is not None
    # Question should mention "product" because Rule 1 targeted that.
    assert "product" in q.lower()
    # One clarification audit entry should have landed.
    clarification_entries = [
        e for e in out["audit_log"]
        if e.get("agent_name") == "clarification_handler"
    ]
    assert len(clarification_entries) == 1
    assert clarification_entries[0]["action"] == "clarification_raised"
    assert clarification_entries[0]["output_summary"] == q


# ── 3. Low confidence + sparse constraints → clarification ───────────


def test_low_confidence_sparse_constraints_triggers_rule_2():
    """Rule 2: confidence < 0.4 AND fewer than 2 concrete constraints → clarify.
    A product_type alone with low confidence still has only 1 constraint."""
    geocoder = _FakeGeocoder((0.0, 0.0))
    registry = _build_registry(geocoder=geocoder)

    finish_payload = {
        "product_type": "something",
        "product_keywords": ["something"],
        "industry_context": None,
        "buyer_intent": "any",
        "category_hint": None,
        "location_city": None,
        "location_country": None,
        "location_region": None,
        "location_radius_km": None,
        "certifications": [],
        "capacity_min": None,
        "capacity_unit": None,
        "lead_time_max_days": None,
        "query_type": "general",
        "complexity": "simple",
        "original_language": "en",
        # Confidence below the floor — but product_type IS set so Rule 1 won't fire.
        "confidence": 0.25,
        "clarification_needed": False,
        "clarification_question": None,
    }
    llm = _FakeLLM([
        f'Thought: Finishing with low confidence.\nAction: Finish\nAction Input: {json.dumps(finish_payload)}',
        # Clarification-composer LLM call.
        "Could you say more about certifications or country?",
    ])
    parser = _make_parser(llm, registry)

    out = parser.execute(_make_state("we need something for the warehouse"))

    assert out["needs_clarification"] is True
    assert out["clarification_question"] is not None
    assert out["pipeline_status"] == "needs_clarification"


# ── 4. Memory hit suppresses Rule 1 even when product is missing ─────


def test_memory_hit_suppresses_clarification_when_product_missing():
    """If lookup_past_query came back with a non-empty memory row, Rule 1
    must NOT fire — memory is taken as helpful context. The Parser is
    trusted to merge that context in downstream and proceed.
    """
    geocoder = _FakeGeocoder((0.0, 0.0))

    def _lookup_fn(query_text: str, top_k: int = 3) -> list[dict[str, Any]]:
        # A prior packaging query is "remembered" — Rule 1 should now stay quiet.
        return [
            {
                "memory_id": "m-1",
                "score": 0.7,
                "query_text": "ISO 9001 packaging Germany",
                "constraints": {
                    "product_type": "packaging",
                    "certifications": ["ISO 9001"],
                },
            }
        ]

    registry = _build_registry(geocoder=geocoder, lookup_fn=_lookup_fn)

    finish_payload = {
        "product_type": None,
        "product_keywords": [],
        "industry_context": None,
        "buyer_intent": "any",
        "category_hint": None,
        "location_city": None,
        "location_country": "Germany",  # → adds 1 constraint
        "location_region": None,
        "location_radius_km": None,
        "certifications": ["ISO 9001"],  # → adds 1 constraint
        "capacity_min": None,
        "capacity_unit": None,
        "lead_time_max_days": None,
        "query_type": "general",
        "complexity": "simple",
        "original_language": "en",
        "confidence": 0.6,  # above the floor; Rule 2 won't fire either
        "clarification_needed": False,
        "clarification_question": None,
    }
    llm = _FakeLLM([
        'Thought: Memory might help.\nAction: lookup_past_query\nAction Input: {"query_text": "same as last time", "top_k": 3}',
        f'Thought: Using memory.\nAction: Finish\nAction Input: {json.dumps(finish_payload)}',
    ])
    parser = _make_parser(llm, registry)

    out = parser.execute(_make_state("same as last time"))

    # No clarification because memory was useful.
    assert out["needs_clarification"] is False
    assert out["clarification_question"] is None
    assert out["pipeline_status"] == "running"


# ── 5. Fallback path (max_iterations) is not double-clarified ────────


def test_fallback_path_keeps_its_own_clarification_message():
    """When the ReAct loop terminates via max_iterations, `_fallback_extract`
    writes its own clarification text. The post-loop trigger MUST NOT run a
    second LLM call to overwrite that — degraded paths own their messaging.
    """
    from app.agents.parser_agent import MAX_REACT_ITERATIONS

    # Failing geocoder so the trace recovers nothing — a productive trace
    # would now proceed without clarification (Task 3.4 fallback upgrade).
    geocoder = _FakeGeocoder(RuntimeError("nominatim down"))
    registry = _build_registry(geocoder=geocoder)

    # Every response is a fresh geocode call so dedup never fires; loop drains.
    responses = [
        f'Thought: Step {i}.\nAction: geocode_location\nAction Input: {{"location_name": "Place{i}"}}'
        for i in range(MAX_REACT_ITERATIONS + 1)
    ]
    llm = _FakeLLM(responses)
    parser = _make_parser(llm, registry)

    out = parser.execute(_make_state("bronze supplier near Bremen ISO 9001"))

    assert out["react_terminated_by"] == "max_iterations"
    assert out["needs_clarification"] is True
    # The fallback message — distinguishable from the Task 3.3 composer output.
    assert "reasoning budget" in (out["clarification_question"] or "")
    # No clarification_handler audit entry was appended on the fallback path.
    clarification_entries = [
        e for e in out["audit_log"]
        if e.get("agent_name") == "clarification_handler"
    ]
    assert clarification_entries == []


# -- 6. Legacy Finish-payload clarification is audited (Task 3.4 regression) --


def test_legacy_finish_payload_clarification_writes_audit_entry():
    """Task 3.4 smoke found: when the LLM itself sets clarification_needed
    in its Finish payload (instead of the post-loop composer firing), the
    Parser raised a resumable clarification with NO clarification_raised
    audit row. Both origins must be audited identically."""
    registry = _build_registry(geocoder=_FakeGeocoder((48.1, 11.5)))

    finish_payload = {
        "product_type": "packaging",
        "product_keywords": ["packaging"],
        "industry_context": "packaging",
        "buyer_intent": "manufacturer",
        "category_hint": "packaging",
        "location_city": None,
        "location_country": None,
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
        "clarification_needed": True,
        "clarification_question": "Which country should the supplier be in?",
    }
    llm = _FakeLLM([
        f'Thought: Done but ambiguous.\nAction: Finish\nAction Input: {json.dumps(finish_payload)}',
    ])
    parser = _make_parser(llm, registry)

    out = parser.execute(_make_state("packaging supplier somewhere"))

    assert out["needs_clarification"] is True
    assert out["clarification_question"] == "Which country should the supplier be in?"
    entries = [
        e for e in out["audit_log"]
        if e.get("agent_name") == "clarification_handler"
        and e.get("action") == "clarification_raised"
    ]
    assert len(entries) == 1, (
        f"legacy-path clarification must be audited; audit_log={out['audit_log']}"
    )
    assert "Finish payload" in (entries[0].get("reasoning") or "")


# -- 7. Rule 1 placeholder pollution fix (Development Plan, Phase 0) ----------


@pytest.mark.parametrize("polluted", [
    "our project",
    "my needs",
    "supplier",
    "materials for our project",
    "The Usual",
])
def test_is_placeholder_product_matches_contentless_values(polluted):
    from app.agents.parser_agent import _is_placeholder_product
    assert _is_placeholder_product(polluted) is True


@pytest.mark.parametrize("real_product", [
    "packaging materials",
    "stainless steel fasteners",
    "cardboard boxes",
    "textile dyeing services",
])
def test_is_placeholder_product_keeps_real_products(real_product):
    from app.agents.parser_agent import _is_placeholder_product
    assert _is_placeholder_product(real_product) is False


def test_placeholder_product_type_is_nulled_and_rule_1_fires():
    """LLM copies "our project" into product_type. The normaliser must null
    it (semantic search for "our project" is noise) and Rule 1 must then
    raise a product clarification despite the non-empty payload value."""
    registry = _build_registry(geocoder=_FakeGeocoder((0.0, 0.0)))

    finish_payload = {
        "product_type": "our project",
        "product_keywords": [],
        "industry_context": None,
        "buyer_intent": "any",
        "category_hint": None,
        "location_city": None,
        "location_country": None,
        "location_region": None,
        "location_radius_km": None,
        "certifications": [],
        "capacity_min": None,
        "capacity_unit": None,
        "lead_time_max_days": None,
        "query_type": "general",
        "complexity": "simple",
        "original_language": "en",
        "confidence": 0.7,
        "clarification_needed": False,
        "clarification_question": None,
    }
    llm = _FakeLLM([
        f'Thought: Done.\nAction: Finish\nAction Input: {json.dumps(finish_payload)}',
        "What product are you sourcing for the project?",  # composer call
    ])
    parser = _make_parser(llm, registry)

    # Query has real content words so the pre-loop gate does NOT fire; the
    # pollution arrives via the LLM payload, which is the bug under test.
    out = parser.execute(_make_state("sourcing for our project in the chemical sector"))

    assert out["parsed_constraints"]["product_type"] is None
    assert out["needs_clarification"] is True
    assert "product" in (out["clarification_question"] or "").lower()


# -- 8. Pre-loop contentless-query gate (Task 3.4) ----------------------------


def test_contentless_query_raises_clarification_without_react_loop():
    """"I need a supplier" carries zero signal. The Parser must ask up front:
    one composer LLM call, no ReAct iterations, resumable termination type."""
    registry = _build_registry(geocoder=_FakeGeocoder((0.0, 0.0)))
    llm = _FakeLLM([
        "What product or service do you need a supplier for?",  # composer only
    ])
    parser = _make_parser(llm, registry)

    out = parser.execute(_make_state("I need a supplier"))

    assert out["needs_clarification"] is True
    assert out["react_terminated_by"] == "pre_loop_clarification"
    assert out["react_trace"] == []
    assert len(llm.calls) == 1, "only the question composer may call the LLM"
    clarification_entries = [
        e for e in out["audit_log"]
        if e.get("agent_name") == "clarification_handler"
        and e.get("action") == "clarification_raised"
    ]
    assert len(clarification_entries) == 1


def test_content_bearing_query_skips_the_pre_loop_gate():
    from app.agents.parser_agent import _is_contentless_query
    assert _is_contentless_query("I need a supplier") is True
    assert _is_contentless_query("We need materials for our project") is True
    assert _is_contentless_query("Find ISO certified packaging in Bavaria") is False
    assert _is_contentless_query("fabric suppliers") is False
