"""Unit tests for QueryMemoryService (Task 3.2 / Component A).

These tests use a dedicated test collection (`query_memory_pytest`) and a
deterministic FakeEmbedding client so the suite stays offline and fast.
Test 3 (semantic retrieval) uses a tiny token-overlap-aware fake embedding
that is good enough to show paraphrase handling without burning Voyage's
free-tier 3 RPM budget.

The 5 tests pinned here match Task 3.2's Component D contract:

  1. Empty memory → empty result
  2. Self-isolation (cross-user leakage)
  3. Semantic retrieval (paraphrase)
  4. Similarity threshold filters noise
  5. End-to-end memory hop via the Parser's ReAct loop using FakeLLM
     (a 6th lookup_past_query-tool test pins the closure user_id binding)

Test 5 is the killer test — it proves Q2 can call lookup_past_query and
have the result merged into the final parsed_constraints.
"""

from __future__ import annotations

import json
import math
import re
import time
import uuid
from typing import Any

import pytest

from app.agents.parser_agent import ParserAgent
from app.agents.tools import ToolRegistry
from app.agents.tools.cert_taxonomy import canonicalize_certification_tool
from app.agents.tools.geocode import geocode_location_tool
from app.agents.tools.industry_context import infer_industry_context_tool
from app.agents.tools.past_query import make_lookup_past_query_tool
from app.agents.tools.quantity_parser import parse_quantity_unit_tool
from app.core.embeddings import EMBEDDING_DIM
from app.services.query_memory import QueryMemoryService


# ── Fakes ────────────────────────────────────────────────────────────────


class _FakeEmbedding:
    """Deterministic token-overlap embedding for offline tests.

    Hashes each lowercased token into a fixed-size float vector. Two queries
    that share many tokens produce vectors whose cosine similarity is high;
    unrelated queries produce nearly orthogonal vectors. That is enough to
    demonstrate paraphrase handling without hitting Voyage.
    """

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    def _tokens(self, text: str) -> list[str]:
        return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t]

    def embed_one(self, text: str, input_type: str = "document") -> list[float]:
        vec = [0.0] * self.dim
        for tok in self._tokens(text):
            # Hash the token to a stable index + sign; magnitudes accumulate
            # when the same token appears across two queries → higher cosine.
            h = abs(hash(tok))
            idx = h % self.dim
            sign = 1.0 if (h >> 16) & 1 else -1.0
            vec[idx] += sign
        # L2-normalise so cosine similarity is just the dot product.
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class _FakeLLM:
    """Same scripted-LLM helper as test_parser_react — local copy keeps the
    test file self-contained and easier to read in isolation."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages, **kwargs):
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("FakeLLM script exhausted")
        return self.responses.pop(0)


# ── Fixtures ────────────────────────────────────────────────────────────


_TEST_COLLECTION = f"query_memory_pytest_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def memory_service():
    """A fresh QueryMemoryService bound to an isolated test collection."""
    svc = QueryMemoryService(
        embedding_client=_FakeEmbedding(),
        collection_name=_TEST_COLLECTION,
    )
    svc._reset_for_tests()
    yield svc
    # Best-effort cleanup; don't fail the suite if Milvus already gone.
    try:
        svc._reset_for_tests()
    except Exception:
        pass


# ── 1. Empty memory → empty result ──────────────────────────────────────


def test_empty_memory_returns_empty_list(memory_service):
    out = memory_service.search(
        user_id="user-with-no-history",
        query_text="ISO 9001 packaging supplier in Germany",
    )
    assert out == []


# ── 2. Self-isolation (privacy boundary) ────────────────────────────────


def test_user_b_cannot_see_user_a_memory(memory_service):
    """The Milvus expr filter is the hard privacy boundary. Even with an
    identical query text, user B must never see user A's row."""
    user_a = "user-a-" + uuid.uuid4().hex[:8]
    user_b = "user-b-" + uuid.uuid4().hex[:8]

    memory_service.write(
        user_id=user_a,
        query_text="ISO 9001 packaging supplier in Germany",
        parsed_constraints={"product_type": "packaging", "location_country": "Germany"},
    )

    a_hits = memory_service.search(
        user_id=user_a,
        query_text="ISO 9001 packaging supplier in Germany",
    )
    b_hits = memory_service.search(
        user_id=user_b,
        query_text="ISO 9001 packaging supplier in Germany",
    )

    assert len(a_hits) == 1, "Owner must see their own memory"
    assert a_hits[0]["similarity"] > 0.95
    assert b_hits == [], "Cross-user leakage detected — privacy boundary failed"


# ── 3. Semantic retrieval (paraphrase) ──────────────────────────────────


def test_paraphrase_query_retrieves_original(memory_service):
    user_id = "user-paraphrase-" + uuid.uuid4().hex[:8]
    memory_service.write(
        user_id=user_id,
        query_text="ISO 9001 packaging supplier in Germany",
        parsed_constraints={
            "product_type": "packaging",
            "certifications": ["ISO 9001"],
            "location_country": "Germany",
        },
    )

    # Paraphrase shares the load-bearing tokens: ISO 9001, packaging, Germany.
    hits = memory_service.search(
        user_id=user_id,
        query_text="packaging supplier ISO 9001 Germany",
        top_k=3,
        min_similarity=0.5,
    )
    assert len(hits) == 1
    assert hits[0]["similarity"] >= 0.5
    assert hits[0]["constraints"]["certifications"] == ["ISO 9001"]


# ── 4. Similarity threshold filters noise ───────────────────────────────


def test_unrelated_query_filtered_by_threshold(memory_service):
    user_id = "user-threshold-" + uuid.uuid4().hex[:8]
    memory_service.write(
        user_id=user_id,
        query_text="ISO 9001 packaging supplier in Germany",
        parsed_constraints={"product_type": "packaging"},
    )

    hits = memory_service.search(
        user_id=user_id,
        query_text="best pizza in Berlin tonight",
        min_similarity=0.65,
    )
    assert hits == [], "Unrelated query should not cross the similarity threshold"


# ── 5. End-to-end memory hop via the Parser ReAct loop ─────────────────


def test_memory_hop_q2_retrieves_q1_and_merges_with_new_location(memory_service):
    """The thesis killer test: Q1 establishes context, Q2 leans on memory.

    Q1 is written manually (we don't drive the full pipeline here — that lives
    in scripts/memory_demo.py). Q2 then runs through a real ParserAgent whose
    lookup_past_query tool is bound to the test user. The scripted FakeLLM
    chooses lookup_past_query first, sees Q1's constraints in the Observation,
    then finishes with product/cert/capacity copied from Q1 + location=Bavaria
    from Q2."""

    user_id = "user-hop-" + uuid.uuid4().hex[:8]

    q1_constraints = {
        "product_type": "packaging supplier",
        "product_keywords": ["packaging", "ISO 9001"],
        "industry_context": "packaging",
        "buyer_intent": "manufacturer",
        "category_hint": "packaging",
        "location_country": "Germany",
        "certifications": ["ISO 9001"],
        "capacity_min": 10000.0,
        "capacity_unit": "units/month",
        "query_type": "capability_match",
        "complexity": "medium",
        "original_language": "en",
    }
    memory_service.write(
        user_id=user_id,
        query_text="ISO 9001 certified packaging supplier in Germany with 10000 units per month capacity",
        parsed_constraints=q1_constraints,
    )

    # Build the registry the way Component C does it — closure-bound user_id
    # on the lookup_past_query tool so the LLM cannot point at another user.
    registry = ToolRegistry()
    registry.register(geocode_location_tool(_geocoder=_StaticGeocoder((48.137, 11.575))))
    registry.register(canonicalize_certification_tool())
    registry.register(infer_industry_context_tool(_llm=_FakeLLM(["{}"])))
    registry.register(parse_quantity_unit_tool())
    registry.register(
        make_lookup_past_query_tool(
            memory_service=memory_service,
            current_user_id=user_id,
            # The token-hash FakeEmbedding gives Q2 ("Same product as last
            # time but in Bavaria") near-zero overlap with Q1. Real Voyage
            # embeddings handle this paraphrase comfortably (Voyage cosine
            # demoed in the live trace); for this offline structural test we
            # drop the similarity floor to 0 so the wiring is what's pinned.
            min_similarity=0.0,
        )
    )

    finish_payload = {
        "product_type": "packaging supplier",
        "product_keywords": ["packaging", "ISO 9001"],
        "industry_context": "packaging",
        "buyer_intent": "manufacturer",
        "category_hint": "packaging",
        "location_city": None,
        "location_country": "Germany",
        "location_region": "Bavaria",
        "location_radius_km": None,
        "certifications": ["ISO 9001"],
        "capacity_min": 10000,
        "capacity_unit": "units/month",
        "lead_time_max_days": None,
        "query_type": "capability_match",
        "complexity": "medium",
        "original_language": "en",
        "confidence": 0.9,
        "clarification_needed": False,
        "clarification_question": None,
    }
    llm = _FakeLLM(
        [
            'Thought: The user said "same as last time" — look up prior context.\n'
            'Action: lookup_past_query\n'
            'Action Input: {"query_text": "Same product as last time but in Bavaria"}',
            'Thought: Geocode Bavaria so downstream search has coordinates.\n'
            'Action: geocode_location\n'
            'Action Input: {"location_name": "Bavaria"}',
            'Thought: I have enough — merge Q1 product/cert/capacity with Q2 location.\n'
            'Action: Finish\n'
            'Action Input: ' + json.dumps(finish_payload),
        ]
    )

    parser = ParserAgent(tool_registry=registry)
    parser.llm = llm  # type: ignore[assignment]

    state = {
        "raw_query": "Same product as last time but in Bavaria",
        "query_id": "q2-hop-test",
        "user_id": "",  # skips the legacy memory-loader; closure handles user binding
        "audit_log": [],
        "search_scope": "approved_only",
    }
    out = parser.execute(state)

    trace = out["react_trace"]
    actions = [step["action"] for step in trace]
    assert "lookup_past_query" in actions, (
        f"Parser did not consult memory; actions={actions}"
    )
    lookup_step = next(s for s in trace if s["action"] == "lookup_past_query")
    obs = lookup_step["observation"]
    assert isinstance(obs, list) and obs, (
        "lookup_past_query observation should be a non-empty list when Q1 exists"
    )
    assert obs[0]["constraints"]["product_type"] == "packaging supplier"
    assert "ISO 9001" in obs[0]["constraints"]["certifications"]

    constraints = out["parsed_constraints"]
    # Q1 fields preserved.
    assert constraints["product_type"] == "packaging supplier"
    assert "ISO 9001" in constraints["certifications"]
    assert constraints["capacity_min"] == 10000
    assert constraints["capacity_unit"] == "units/month"
    # Q2's new location overrides.
    assert constraints["location_region"] == "Bavaria"


# ── 6. Closure-bound user_id (privacy hardening) ────────────────────────


def test_lookup_tool_ignores_user_id_override_attempt(memory_service):
    """Even if the LLM puts `user_id` in Action Input, the tool's closure
    binding wins. This is the structural invariant Risk 1 hinges on."""
    owner = "owner-" + uuid.uuid4().hex[:8]
    attacker = "attacker-" + uuid.uuid4().hex[:8]
    memory_service.write(
        user_id=owner,
        query_text="ISO 9001 packaging Germany",
        parsed_constraints={"product_type": "packaging"},
    )

    tool_bound_to_attacker = make_lookup_past_query_tool(
        memory_service=memory_service,
        current_user_id=attacker,
    )
    # The LLM tries to spoof the owner's id — the kwarg is dropped silently.
    result = tool_bound_to_attacker.fn(
        query_text="ISO 9001 packaging Germany",
        user_id=owner,  # malicious override attempt
    )
    assert result == [], "Closure binding failed — leaked another user's memory"


# ── Helpers (kept at the bottom so the test bodies are the visible story) ──


class _StaticGeocoder:
    def __init__(self, result):
        self.result = result

    def geocode(self, name: str):
        return self.result
