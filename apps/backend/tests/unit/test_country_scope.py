from __future__ import annotations

from typing import Any

import pytest

from app.agents import orchestrator
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
def test_city_region_or_positive_radius_counts_as_local_scope(
    field: str,
    value: object,
) -> None:
    assert has_local_scope(_constraints(**{field: value})) is True


def test_country_centroid_and_bounds_do_not_count_as_local_scope() -> None:
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
def test_countrywide_phrases_are_detected(raw_query: str) -> None:
    assert requests_countrywide_scope(raw_query, "Canada") is True


def test_plain_country_mention_is_not_countrywide_intent() -> None:
    assert requests_countrywide_scope(
        "Find industrial pump suppliers in Canada",
        "Canada",
    ) is False


def test_interactive_country_only_query_needs_scope() -> None:
    assert needs_country_scope_clarification(
        constraints=_constraints(),
        raw_query="Find industrial pump suppliers in Canada",
        benchmark_supplier_ids=[],
        turn_number=1,
        max_turns=3,
    ) is True


def test_fixed_corpus_evaluation_bypasses_scope_gate() -> None:
    assert needs_country_scope_clarification(
        constraints=_constraints(),
        raw_query="Find industrial pump suppliers in Canada",
        benchmark_supplier_ids=["supplier-1"],
        turn_number=1,
        max_turns=3,
    ) is False


def test_final_turn_fails_open_to_countrywide_scope() -> None:
    assert needs_country_scope_clarification(
        constraints=_constraints(),
        raw_query="User clarification: just find the best ones",
        benchmark_supplier_ids=[],
        turn_number=3,
        max_turns=3,
    ) is False


def test_question_uses_the_parsed_country() -> None:
    assert country_scope_question("Canada") == (
        "Which city or region should I search near, or should I search all of Canada?"
    )


def test_initial_state_wires_benchmark_supplier_ids_to_parser_state() -> None:
    state = orchestrator._create_initial_state(
        raw_query="Find industrial pump suppliers in Canada",
        query_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        search_scope="both",
        benchmark_supplier_ids=["supplier-1"],
    )

    assert state["benchmark_supplier_ids"] == ["supplier-1"]
