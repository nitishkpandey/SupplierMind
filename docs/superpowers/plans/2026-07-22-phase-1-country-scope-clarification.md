# Phase 1 Country-Scope Clarification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deterministically pause interactive product-plus-country queries for local scope on clean and degraded parser paths, resume them safely, and preserve SupplierBench fixed-corpus behavior.

**Architecture:** Put country-scope policy in a small pure module, then let `ParserAgent` apply it after normalized constraints exist regardless of ReAct termination. Mark only genuinely resumable clarifications in shared state so `parser_node` can persist a degraded country-scope pause without changing the existing fail-safe behavior for other degraded parser errors.

**Tech Stack:** Python 3.11, LangGraph state dictionaries, SQLAlchemy clarification repository, pytest, Ruff, mypy.

## Global Constraints

- Work only in `/Users/nitishkumarpandey/Desktop/SupplierMind` on `production/agentic-suppliermind`.
- Phase 1 only: do not change quantity-tool behavior, Tavily queries, localized query families, audit diagnostics, demo seed data, compliance, ranking, or SupplierBench data.
- The policy must be generic across products, services, and countries; do not hard-code beer, breweries, Germany, or benchmark query text.
- Only `location_city`, `location_region`, and a positive `location_radius_km` satisfy local scope; country centroid coordinates and country bounds do not.
- A non-empty `benchmark_supplier_ids` list bypasses only the country-scope clarification and retains `location_country` as a hard constraint.
- Turn 1 may ask, turn 2 may re-ask once, and turn 3 must proceed country-wide using `MAX_CLARIFICATION_TURNS = 3`.
- Keep strict product, location, certification, sanctions, capacity, and lead-time enforcement unchanged.

---

### Task 1: Isolate the pure country-scope policy

**Files:**
- Create: `apps/backend/app/agents/country_scope.py`
- Create: `apps/backend/tests/unit/test_country_scope.py`

**Interfaces:**
- Consumes: normalized `Mapping[str, Any]` parser constraints, raw user text, `benchmark_supplier_ids`, `turn_number`, and `MAX_CLARIFICATION_TURNS`.
- Produces: `has_local_scope(constraints) -> bool`, `requests_countrywide_scope(raw_query, country) -> bool`, `needs_country_scope_clarification(...) -> bool`, and `country_scope_question(country) -> str`.

- [ ] **Step 1: Write failing pure-policy tests**

Create `apps/backend/tests/unit/test_country_scope.py` with:

```python
from __future__ import annotations

from typing import Any

import pytest

from app.agents.country_scope import (
    country_scope_question,
    has_local_scope,
    needs_country_scope_clarification,
    requests_countrywide_scope,
)


def _constraints(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "product_type": "industrial pumps",
        "location_country": "Canada",
        "location_city": None,
        "location_region": None,
        "location_radius_km": None,
        "location_lat": 56.1304,
        "location_lng": -106.3468,
        "location_bounds": [41.6766, -141.0027, 83.3362, -52.3232],
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("location_city", "Toronto"),
        ("location_region", "Ontario"),
        ("location_radius_km", 75),
    ],
)
def test_city_region_or_positive_radius_counts_as_local_scope(field: str, value: object):
    assert has_local_scope(_constraints(**{field: value})) is True


def test_country_centroid_and_bounds_do_not_count_as_local_scope():
    assert has_local_scope(_constraints()) is False


@pytest.mark.parametrize(
    "raw_query",
    [
        "Find industrial pump suppliers country-wide",
        "Find industrial pump suppliers nationwide",
        "Find industrial pump suppliers throughout Canada",
        "Find industrial pump suppliers across Canada",
        "Find industrial pump suppliers anywhere in Canada",
        "Find industrial pump suppliers in all of Canada",
        "Find industrial pump suppliers Canada-wide",
    ],
)
def test_countrywide_phrases_are_detected(raw_query: str):
    assert requests_countrywide_scope(raw_query, "Canada") is True


def test_plain_country_mention_is_not_countrywide_intent():
    assert requests_countrywide_scope(
        "Find industrial pump suppliers in Canada",
        "Canada",
    ) is False


def test_interactive_country_only_query_needs_scope():
    assert needs_country_scope_clarification(
        constraints=_constraints(),
        raw_query="Find industrial pump suppliers in Canada",
        benchmark_supplier_ids=[],
        turn_number=1,
        max_turns=3,
    ) is True


def test_fixed_corpus_evaluation_bypasses_scope_gate():
    assert needs_country_scope_clarification(
        constraints=_constraints(),
        raw_query="Find industrial pump suppliers in Canada",
        benchmark_supplier_ids=["supplier-1"],
        turn_number=1,
        max_turns=3,
    ) is False


def test_final_turn_fails_open_to_countrywide_scope():
    assert needs_country_scope_clarification(
        constraints=_constraints(),
        raw_query="User clarification: just find the best ones",
        benchmark_supplier_ids=[],
        turn_number=3,
        max_turns=3,
    ) is False


def test_question_uses_the_parsed_country():
    assert country_scope_question("Canada") == (
        "Which city or region should I search near, or should I search all of Canada?"
    )
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
cd apps/backend
.venv/bin/pytest tests/unit/test_country_scope.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.agents.country_scope'`.

- [ ] **Step 3: Implement the minimal pure policy**

Create `apps/backend/app/agents/country_scope.py`:

```python
"""Deterministic country-scope clarification policy."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.utils.text_normalization import strip_accents

_LOCAL_SCOPE_KEYS = ("location_city", "location_region", "location_radius_km")
_GENERIC_COUNTRYWIDE_RE = re.compile(
    r"\b(?:country[\s-]?wide|nation[\s-]?wide)\b",
    re.IGNORECASE,
)


def _normalise_text(value: object) -> str:
    return " ".join(strip_accents(str(value or "")).casefold().split())


def has_local_scope(constraints: Mapping[str, Any]) -> bool:
    """Return true only for city, region, or a positive radius."""
    if any(constraints.get(key) for key in _LOCAL_SCOPE_KEYS[:2]):
        return True
    try:
        return float(constraints.get("location_radius_km") or 0) > 0
    except (TypeError, ValueError):
        return False


def requests_countrywide_scope(raw_query: str, country: object) -> bool:
    """Detect explicit nationwide intent without treating `in COUNTRY` as enough."""
    text = _normalise_text(raw_query)
    if _GENERIC_COUNTRYWIDE_RE.search(text):
        return True

    country_text = _normalise_text(country)
    if not country_text:
        return False
    escaped_country = re.escape(country_text)
    country_patterns = (
        rf"\b{escaped_country}[\s-]?wide\b",
        rf"\b(?:throughout|across|anywhere\s+in)\s+(?:the\s+)?{escaped_country}\b",
        rf"\ball\s+(?:of\s+)?(?:the\s+)?{escaped_country}\b",
    )
    return any(re.search(pattern, text) for pattern in country_patterns)


def needs_country_scope_clarification(
    *,
    constraints: Mapping[str, Any],
    raw_query: str,
    benchmark_supplier_ids: Sequence[str],
    turn_number: int,
    max_turns: int,
) -> bool:
    """Return true when an interactive product+country query needs local scope."""
    if benchmark_supplier_ids or turn_number >= max_turns:
        return False
    product = constraints.get("product_type")
    country = constraints.get("location_country")
    if not product or not country or has_local_scope(constraints):
        return False
    return not requests_countrywide_scope(raw_query, country)


def country_scope_question(country: object) -> str:
    """Build the one-sentence deterministic scope question."""
    country_text = " ".join(str(country or "the country").split())
    return (
        "Which city or region should I search near, or should I search all of "
        f"{country_text}?"
    )
```

- [ ] **Step 4: Run the pure tests and verify GREEN**

Run:

```bash
cd apps/backend
.venv/bin/pytest tests/unit/test_country_scope.py -q
```

Expected: all tests in `test_country_scope.py` pass.

- [ ] **Step 5: Commit the isolated policy**

```bash
git add apps/backend/app/agents/country_scope.py apps/backend/tests/unit/test_country_scope.py
git commit -m "feat: add deterministic country scope policy"
```

---

### Task 2: Apply the gate on clean, degraded, resumed, and benchmark parser paths

**Files:**
- Modify: `apps/backend/app/agents/parser_agent.py:1101-1225`
- Modify: `apps/backend/app/agents/parser_agent.py:1282-1289`
- Modify: `apps/backend/app/agents/parser_agent.py:1353-1404`
- Modify: `apps/backend/app/agents/state.py:128-142`
- Modify: `apps/backend/tests/unit/test_parser_clarification.py`
- Modify: `apps/backend/tests/unit/test_parser_react.py:480-610`

**Interfaces:**
- Consumes: Task 1's `needs_country_scope_clarification` and `country_scope_question` functions plus `MAX_CLARIFICATION_TURNS`.
- Produces: `AgentState.clarification_resumable: bool`; deterministic `needs_clarification`, `clarification_question`, and audit state for country scope on every recoverable parser termination.

- [ ] **Step 1: Add failing parser-level regression tests**

In `apps/backend/tests/unit/test_parser_clarification.py`, add a reusable finish payload and runner after `_make_parser`:

```python
def _country_scope_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "product_type": "industrial pumps",
        "product_keywords": ["industrial pumps", "pumps"],
        "industry_context": "industrial machinery",
        "buyer_intent": "manufacturer",
        "category_hint": "machinery",
        "location_city": None,
        "location_country": "Canada",
        "location_region": None,
        "location_lat": 56.1304,
        "location_lng": -106.3468,
        "location_radius_km": None,
        "location_bounds": [41.6766, -141.0027, 83.3362, -52.3232],
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
    payload.update(overrides)
    return payload


def _run_country_scope_finish(
    raw_query: str,
    *,
    payload_overrides: dict[str, Any] | None = None,
    state_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _country_scope_payload(**(payload_overrides or {}))
    llm = _FakeLLM([
        f"Thought: Constraints are parsed.\nAction: Finish\nAction Input: {json.dumps(payload)}"
    ])
    parser = _make_parser(llm, _build_registry(geocoder=_FakeGeocoder((56.1304, -106.3468))))
    state = _make_state(raw_query)
    state.update(state_overrides or {})
    return parser.execute(state)
```

Add these tests:

```python
def test_country_only_query_asks_for_city_region_or_countrywide_scope():
    out = _run_country_scope_finish("Find industrial pump suppliers in Canada")

    assert out["needs_clarification"] is True
    assert out["clarification_resumable"] is True
    assert out["clarification_question"] == (
        "Which city or region should I search near, or should I search all of Canada?"
    )


def test_country_centroid_and_bounds_do_not_suppress_scope_question():
    out = _run_country_scope_finish("Find industrial pump suppliers in Canada")
    assert out["needs_clarification"] is True


@pytest.mark.parametrize(
    ("answer", "payload_overrides"),
    [
        ("Toronto", {"location_city": "Toronto"}),
        ("Ontario", {"location_region": "Ontario"}),
        ("within 75 km of Toronto", {"location_city": "Toronto", "location_radius_km": 75}),
    ],
)
def test_valid_local_scope_answer_resumes_discovery(
    answer: str,
    payload_overrides: dict[str, Any],
):
    out = _run_country_scope_finish(
        f"Find industrial pump suppliers in Canada\n\nUser clarification: {answer}",
        payload_overrides=payload_overrides,
        state_overrides={"turn_number": 2},
    )
    assert out["needs_clarification"] is False
    assert out["pipeline_status"] == "running"


def test_countrywide_answer_resumes_without_dropping_country():
    out = _run_country_scope_finish(
        "Find industrial pump suppliers in Canada\n\nUser clarification: all of Canada",
        state_overrides={"turn_number": 2},
    )
    assert out["needs_clarification"] is False
    assert out["parsed_constraints"]["location_country"] == "Canada"


def test_countrywide_intent_in_original_query_does_not_pause():
    out = _run_country_scope_finish(
        "Find industrial pump suppliers throughout Canada",
    )
    assert out["needs_clarification"] is False
    assert out["parsed_constraints"]["location_country"] == "Canada"


def test_one_unusable_answer_reasks_for_scope():
    out = _run_country_scope_finish(
        "Find industrial pump suppliers in Canada\n\nUser clarification: just find the best ones",
        state_overrides={"turn_number": 2},
    )
    assert out["needs_clarification"] is True


def test_second_unusable_answer_fails_open_on_final_turn():
    out = _run_country_scope_finish(
        "Find industrial pump suppliers in Canada\n\n"
        "User clarification: just find the best ones\n\n"
        "User clarification: use your judgement",
        state_overrides={"turn_number": 3},
    )
    assert out["needs_clarification"] is False
    assert out["parsed_constraints"]["location_country"] == "Canada"


def test_fixed_corpus_country_only_query_does_not_pause():
    out = _run_country_scope_finish(
        "Find industrial pump suppliers in Canada",
        state_overrides={"benchmark_supplier_ids": ["supplier-1"]},
    )
    assert out["needs_clarification"] is False
    assert out["parsed_constraints"]["location_country"] == "Canada"
```

In `apps/backend/tests/unit/test_parser_react.py`, change
`test_fallback_proceeds_when_trace_recovered_product_and_constraint` to assert
that the recovered country-only degraded path pauses and is resumable:

```python
assert out["react_terminated_by"] == "max_iterations"
assert out["needs_clarification"] is True
assert out["clarification_resumable"] is True
assert out["clarification_question"] == (
    "Which city or region should I search near, or should I search all of Germany?"
)
```

Also add the exact production regression while keeping the policy itself
generic:

```python
def test_helles_pilsner_degraded_country_only_query_asks_for_scope():
    registry = _build_registry(geocoder=_FakeGeocoder((51.1657, 10.4515)))
    responses = [
        'Thought: locate.\nAction: geocode_location\nAction Input: {"location_name": "Germany"}',
        'Thought: quantity.\nAction: parse_quantity_unit\nAction Input: {"text": "1000 bottles"}',
        'Thought: package size.\nAction: parse_quantity_unit\nAction Input: {"text": "0.5 l bottles"}',
        'Thought: retry quantity.\nAction: parse_quantity_unit\nAction Input: {"text": "1000 0.5l bottles"}',
        'Thought: industry.\nAction: infer_industry_context\nAction Input: {"product_description": "Helles and Pilsner beer"}',
        'Thought: retry quantity.\nAction: parse_quantity_unit\nAction Input: {"text": "1000 bottles of beer"}',
    ]
    parser = _make_parser(_FakeLLM(responses), registry)

    out = parser.execute(_make_state(
        "i want to buy 1000 (.5l) bottles of helles and Pilsner beer in "
        "Germany for the client who is going to organise the summer party."
    ))

    assert out["react_terminated_by"] == "max_iterations"
    assert out["parsed_constraints"]["product_type"] == "Helles and Pilsner beer"
    assert out["parsed_constraints"]["location_country"] == "Germany"
    assert out["needs_clarification"] is True
    assert out["clarification_resumable"] is True
    assert out["clarification_question"] == (
        "Which city or region should I search near, or should I search all of Germany?"
    )
```

- [ ] **Step 2: Run the parser regressions and verify RED**

Run:

```bash
cd apps/backend
.venv/bin/pytest \
  tests/unit/test_parser_clarification.py::test_country_only_query_asks_for_city_region_or_countrywide_scope \
  tests/unit/test_parser_clarification.py::test_fixed_corpus_country_only_query_does_not_pause \
  tests/unit/test_parser_clarification.py::test_one_unusable_answer_reasks_for_scope \
  tests/unit/test_parser_react.py::test_fallback_proceeds_when_trace_recovered_product_and_constraint \
  tests/unit/test_parser_react.py::test_helles_pilsner_degraded_country_only_query_asks_for_scope -q
```

Expected: failures show the current operational-preference question, missing
`clarification_resumable`, benchmark clarification, and degraded-path bypass.

- [ ] **Step 3: Add resumable clarification state**

In `apps/backend/app/agents/state.py`, add beside `clarification_question`:

```python
clarification_resumable: bool
```

In `_create_initial_state` in `apps/backend/app/agents/orchestrator.py`, add:

```python
clarification_resumable=False,
```

In `_raise_pre_loop_clarification` in `parser_agent.py`, add:

```python
state["clarification_resumable"] = True
```

- [ ] **Step 4: Apply country scope after normalization on every parser path**

Import the policy and existing turn limit in `parser_agent.py`:

```python
from app.agents.country_scope import (
    country_scope_question,
    needs_country_scope_clarification,
)
from app.db.repositories.clarification_repo import MAX_CLARIFICATION_TURNS
```

After constraints and confidence are normalized, compute the deterministic
question before the existing clean-finish clarification logic:

```python
turn_number = int(state.get("turn_number") or 1)
country_scope_needed = needs_country_scope_clarification(
    constraints=constraints,
    raw_query=raw_query,
    benchmark_supplier_ids=state.get("benchmark_supplier_ids") or [],
    turn_number=turn_number,
    max_turns=MAX_CLARIFICATION_TURNS,
)
scope_question = (
    country_scope_question(constraints.get("location_country"))
    if country_scope_needed
    else None
)
```

Keep `_decide_clarification` for missing product/location, low confidence, and
placeholder references, but delete its existing Rule 1e
`operational_preference` block. The new deterministic scope gate owns every
product-plus-country decision, including benchmark bypass and resumed turns.

Replace the final clarification selection with this priority:

```python
if scope_question is not None:
    clarification_needed = True
    clarification_question = scope_question
    composed_question = None
elif use_legacy_location_question:
    clarification_needed = True
    clarification_question = legacy_clarification_question
    composed_question = None
elif composed_question is not None:
    clarification_needed = True
    clarification_question = composed_question
elif terminated_by == "finish":
    clarification_needed = False
    clarification_question = None
else:
    clarification_needed = legacy_clarification_needed
    clarification_question = (
        legacy_clarification_question if clarification_needed else None
    )

clarification_resumable = clarification_needed and (
    terminated_by == "finish" or scope_question is not None
)
```

Store the result with the other parser outputs:

```python
state["clarification_resumable"] = clarification_resumable
```

Audit clean and degraded country-scope pauses by replacing the finish-only audit
condition with:

```python
if clarification_needed and clarification_resumable:
    if scope_question is not None:
        origin = "Deterministic country-scope gate fired"
    elif composed_question is not None:
        origin = "Post-loop trigger fired"
    else:
        origin = "LLM Finish payload requested clarification"
    self._append_audit_entry(
        state,
        agent_name="clarification_handler",
        action="clarification_raised",
        duration_ms=0,
        reasoning=(
            f"{origin}: confidence={confidence:.2f}, "
            f"product_type={constraints.get('product_type')!r}"
        ),
        input_summary=raw_query[:200],
        output_summary=clarification_question or "",
    )
```

- [ ] **Step 5: Update existing tests whose old premise conflicts with the new policy**

Keep non-scope tests focused by making nationwide intent explicit:

```python
# test_clear_query_does_not_trigger_clarification
"ISO 9001 cardboard packaging supplier throughout Germany, 10000 units/month"

# test_finish_payload_treats_purchase_quantities_as_products_not_capacity
"...good and reliable suppliers anywhere in Germany."
```

Rename `test_broad_country_product_query_asks_for_operational_preference` to
`test_broad_country_product_query_asks_for_local_scope`, remove its third fake
LLM response, and assert the exact deterministic city/region/country-wide
question.

Rename `test_resumed_query_with_product_and_country_does_not_ask_optional_preferences`
to `test_resumed_query_without_scope_reasks_once` and assert that turn 2 pauses
with `clarification_resumable is True`.

Leave `test_fallback_path_keeps_its_own_clarification_message` unchanged: it
has no recovered country and must remain a non-resumable degraded failure.

- [ ] **Step 6: Run parser tests and verify GREEN**

Run:

```bash
cd apps/backend
.venv/bin/pytest \
  tests/unit/test_country_scope.py \
  tests/unit/test_parser_clarification.py \
  tests/unit/test_parser_react.py -q
```

Expected: all three files pass; no network calls occur.

- [ ] **Step 7: Commit parser integration**

```bash
git add \
  apps/backend/app/agents/parser_agent.py \
  apps/backend/app/agents/state.py \
  apps/backend/app/agents/orchestrator.py \
  apps/backend/tests/unit/test_parser_clarification.py \
  apps/backend/tests/unit/test_parser_react.py
git commit -m "feat: gate country-only supplier searches"
```

---

### Task 3: Persist degraded country-scope clarification without changing other degraded failures

**Files:**
- Modify: `apps/backend/app/agents/orchestrator.py:142-180`
- Modify: `apps/backend/tests/unit/test_country_scope.py`
- Verify: `apps/backend/tests/unit/test_clarification_endpoint.py:305-365`

**Interfaces:**
- Consumes: `AgentState.clarification_resumable` from Task 2.
- Produces: a `clarification_id` for clean, pre-loop, and degraded country-scope pauses; legacy degraded non-resumable paths still have no row and follow the existing API fail-safe.

- [ ] **Step 1: Write failing parser-node persistence tests**

Add this import with the existing `app.agents` imports in
`apps/backend/tests/unit/test_country_scope.py`:

```python
from app.agents import orchestrator
```

Then append:

```python
def _parser_node_state(*, resumable: bool) -> dict[str, Any]:
    return {
        "raw_query": "Find industrial pump suppliers in Canada",
        "query_id": "00000000-0000-0000-0000-000000000001",
        "user_id": "00000000-0000-0000-0000-000000000002",
        "needs_clarification": True,
        "clarification_resumable": resumable,
        "clarification_question": (
            "Which city or region should I search near, or should I search all of Canada?"
        ),
        "react_terminated_by": "max_iterations",
        "parsed_constraints": {
            "product_type": "industrial pumps",
            "location_country": "Canada",
        },
        "react_trace": [],
        "audit_log": [],
    }


def test_parser_node_persists_resumable_degraded_scope_question(monkeypatch):
    class FakeParserAgent:
        def __init__(self, tool_registry=None):
            self.tool_registry = tool_registry

        def run(self, state):
            return state

    persisted: list[dict[str, Any]] = []

    def fake_persist(state):
        persisted.append(state)
        state["clarification_id"] = "clarification-1"

    monkeypatch.setattr(orchestrator, "build_user_registry", lambda user_id: object())
    monkeypatch.setattr(orchestrator, "ParserAgent", FakeParserAgent)
    monkeypatch.setattr(orchestrator, "_persist_clarification_for_state", fake_persist)

    out = orchestrator.parser_node(_parser_node_state(resumable=True))

    assert persisted == [out]
    assert out["clarification_id"] == "clarification-1"


def test_parser_node_does_not_persist_nonresumable_degraded_failure(monkeypatch):
    class FakeParserAgent:
        def __init__(self, tool_registry=None):
            self.tool_registry = tool_registry

        def run(self, state):
            return state

    persisted: list[dict[str, Any]] = []
    monkeypatch.setattr(orchestrator, "build_user_registry", lambda user_id: object())
    monkeypatch.setattr(orchestrator, "ParserAgent", FakeParserAgent)
    monkeypatch.setattr(
        orchestrator,
        "_persist_clarification_for_state",
        lambda state: persisted.append(state),
    )

    orchestrator.parser_node(_parser_node_state(resumable=False))

    assert persisted == []


def test_paused_country_scope_stops_before_discovery():
    from langgraph.graph import END

    state = _parser_node_state(resumable=True)
    assert orchestrator.after_parser(state) == END
```

- [ ] **Step 2: Run the persistence tests and verify RED**

Run:

```bash
cd apps/backend
.venv/bin/pytest \
  tests/unit/test_country_scope.py::test_parser_node_persists_resumable_degraded_scope_question \
  tests/unit/test_country_scope.py::test_parser_node_does_not_persist_nonresumable_degraded_failure -q
```

Expected: the resumable degraded test fails because `parser_node` still keys
persistence off `react_terminated_by`.

- [ ] **Step 3: Switch parser-node persistence to the explicit resumable flag**

Replace the termination-name condition in `parser_node` with:

```python
if state.get("needs_clarification") and state.get("clarification_resumable"):
    try:
        _persist_clarification_for_state(state)
    except Exception as e:  # noqa: BLE001 — persistence must never crash pipeline
        logger.error(
            "[orchestrator] failed to persist pending_clarification for "
            "query_id=%s: %s",
            state.get("query_id"),
            e,
        )
```

Update the comment to state that clean, pre-loop, and deterministic degraded
country-scope questions are resumable, while other degraded messages are not.

- [ ] **Step 4: Run persistence and API fail-safe tests and verify GREEN**

Run:

```bash
cd apps/backend
.venv/bin/pytest \
  tests/unit/test_country_scope.py \
  tests/unit/test_clarification_endpoint.py::test_degraded_clarification_fails_query_instead_of_stranding_it \
  tests/unit/test_clarification_endpoint.py::test_resumed_pipeline_reclarification_emits_needs_clarification_event -q
```

Expected: all tests pass. The legacy non-resumable degraded endpoint test still
fails the query rather than emitting an unusable clarification event.

- [ ] **Step 5: Commit degraded-path persistence**

```bash
git add \
  apps/backend/app/agents/orchestrator.py \
  apps/backend/tests/unit/test_country_scope.py
git commit -m "fix: persist degraded country scope clarification"
```

---

### Task 4: Verify Phase 1 without starting Phase 2

**Files:**
- Verify only: `apps/backend/app/agents/country_scope.py`
- Verify only: `apps/backend/app/agents/parser_agent.py`
- Verify only: `apps/backend/app/agents/orchestrator.py`
- Verify only: `apps/backend/app/agents/state.py`
- Verify only: affected backend tests

**Interfaces:**
- Consumes: the complete Phase 1 behavior from Tasks 1-3.
- Produces: verification evidence that interactive clarification works, benchmark evaluation bypasses it, and no Phase 2 files changed.

- [ ] **Step 1: Run all focused clarification and parser tests**

```bash
cd apps/backend
.venv/bin/pytest \
  tests/unit/test_country_scope.py \
  tests/unit/test_parser_clarification.py \
  tests/unit/test_parser_react.py \
  tests/unit/test_clarification_endpoint.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the full backend suite**

```bash
cd apps/backend
.venv/bin/pytest -q
```

Expected: the full backend suite passes with no new failures.

- [ ] **Step 3: Run static checks**

```bash
cd apps/backend
.venv/bin/ruff check app tests
.venv/bin/mypy app
```

Expected: both commands exit 0 with no errors.

- [ ] **Step 4: Confirm the phase boundary and clean worktree**

```bash
git status --short
git diff --name-only origin/production/agentic-suppliermind...HEAD
git log --oneline --decorate -8
```

Expected: Phase 1 changes are limited to the parser policy, parser/orchestrator
state wiring, and their tests. `web_search.py`, supplier extraction, compliance,
ranking, benchmark JSON, and dataset generation remain unchanged.

- [ ] **Step 5: Stop for Phase 1 review**

Report focused/full test counts, Ruff and mypy results, the exact commits, and
the unchanged Phase 2/deferred files. Do not begin quantity-tool or Tavily work
until Phase 1 is reviewed.
