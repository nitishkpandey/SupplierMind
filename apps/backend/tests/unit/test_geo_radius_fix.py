"""Phase D bug 1 — geo-radius constraint must not be mapped onto the country field.

Two layers, tested independently (no LLM, no DB):
  - Parser (_normalise_constraints): a radius query's geocoded place is a radius
    *centre*, so it belongs in location_city, never location_country.
  - Compliance (_check_supplier): when a radius constraint is active, location is
    enforced by radius matching, so the hard country-equality short-circuit must
    not fire (it was producing "Supplier is in Germany, required country is Berlin").
"""

from app.agents.compliance_agent import ComplianceAgent
from app.agents.discovery_agent import DiscoveryAgent
from app.agents.parser_agent import ParserAgent


def _compliance_agent() -> ComplianceAgent:
    # Skip __init__ so no live LLM client is built; _check_supplier needs no LLM
    # for a radius-only query (no certs).
    agent = ComplianceAgent.__new__(ComplianceAgent)
    agent._short_circuit_count = 0
    agent._llm_supplier_count = 0
    return agent


def _parser() -> ParserAgent:
    return ParserAgent.__new__(ParserAgent)


# ── Parser layer ─────────────────────────────────────────────────────
def test_radius_centre_goes_to_city_not_country():
    # geocode_location bucketed the no-comma place "Berlin" as a country; with a
    # radius present the parser must treat it as the radius centre (a city).
    parser = _parser()
    raw = {
        "product_type": "valves",
        "location_country": "Berlin",
        "location_radius_km": 50,
        "location_lat": 52.52,
        "location_lng": 13.40,
    }
    out = parser._normalise_constraints(raw, trace=[])
    assert out["location_city"] == "Berlin"
    assert out["location_country"] is None
    assert out["location_radius_km"] == 50


def test_plain_country_query_keeps_country():
    # No radius → "Germany" is a genuine country filter and must be preserved.
    parser = _parser()
    raw = {"product_type": "valves", "location_country": "Germany"}
    out = parser._normalise_constraints(raw, trace=[])
    assert out["location_country"] == "Germany"
    assert out["location_radius_km"] is None


def test_radius_with_explicit_city_and_country_keeps_both():
    # "within 50km of Munich, Germany" geocodes to city=Munich, country=Germany.
    # The explicit city must survive; country stays (radius still governs matching).
    parser = _parser()
    raw = {
        "product_type": "valves",
        "location_city": "Munich",
        "location_country": "Germany",
        "location_radius_km": 50,
        "location_lat": 48.14,
        "location_lng": 11.58,
    }
    out = parser._normalise_constraints(raw, trace=[])
    assert out["location_city"] == "Munich"
    assert out["location_radius_km"] == 50


def test_region_bounds_are_restored_from_geocode_trace():
    parser = _parser()
    out = parser._normalise_constraints(
        {"product_type": "office furniture", "location_region": "Bavaria"},
        trace=[{
            "action": "geocode_location",
            "action_input": {"location_name": "Bavaria"},
            "observation": {
                "found": True,
                "lat": 48.79,
                "lng": 11.50,
                "region": "Bavaria",
                "bounds": [47.27, 8.98, 50.57, 13.84],
            },
        }],
        raw_query="Find office furniture suppliers in Bavaria",
    )

    assert out["location_bounds"] == [47.27, 8.98, 50.57, 13.84]


# ── Compliance layer ─────────────────────────────────────────────────
def test_radius_query_does_not_emit_spurious_country_fail():
    agent = _compliance_agent()
    supplier = {
        "id": "s1", "name": "Brandenburg Valves",
        "country": "Germany", "certifications": [], "lead_time_days": None,
    }
    constraints = {
        "location_radius_km": 50,
        "location_country": "Berlin",   # mis-bucketed centre (defence-in-depth)
        "location_lat": 52.52, "location_lng": 13.40,
    }
    result = agent._check_supplier(supplier, constraints, geo_distance=20.0)
    statuses = {r["constraint_name"]: r["status"] for r in result["compliance_results"]}
    assert "country" not in statuses              # no country-equality verdict
    assert statuses.get("location_radius") == "PASS"
    assert result["overall_pass"] is True


def test_plain_country_mismatch_still_fails():
    # Regression guard: with no radius, a real country mismatch must still FAIL.
    agent = _compliance_agent()
    supplier = {
        "id": "s2", "name": "Lyon Metals",
        "country": "France", "certifications": [], "lead_time_days": None,
    }
    constraints = {"location_country": "Germany"}
    result = agent._check_supplier(supplier, constraints, geo_distance=None)
    statuses = {r["constraint_name"]: r["status"] for r in result["compliance_results"]}
    assert statuses.get("country") == "FAIL"
    assert result["overall_pass"] is False


def test_literal_null_country_is_treated_as_missing():
    agent = _compliance_agent()
    supplier = {
        "id": "s3", "name": "Unverified Metals",
        "country": "null", "certifications": [], "lead_time_days": None,
    }
    constraints = {"location_country": "Germany"}

    result = agent._check_supplier(supplier, constraints, geo_distance=None)

    statuses = {r["constraint_name"]: r["status"] for r in result["compliance_results"]}
    assert "country" not in statuses
    assert result["overall_pass"] is True


def test_radius_hard_filter_removes_semantic_candidate_outside_radius():
    retained, distances, diagnostic = DiscoveryAgent._filter_candidate_rows_by_geography(
        rows=[("near", 52.6, 13.5), ("far", 51.2, 6.8)],
        constraints={
            "location_lat": 52.52,
            "location_lng": 13.40,
            "location_radius_km": 100,
        },
    )

    assert retained == ["near"]
    assert "far" not in distances
    assert diagnostic is None


def test_bavaria_bounds_remove_non_bavarian_candidates():
    retained, _, diagnostic = DiscoveryAgent._filter_candidate_rows_by_geography(
        rows=[("munich", 48.137, 11.575), ("berlin", 52.52, 13.405)],
        constraints={
            "location_region": "Bavaria",
            "location_bounds": [47.27, 8.98, 50.57, 13.84],
        },
    )

    assert retained == ["munich"]
    assert diagnostic is None


def test_region_without_verified_bounds_returns_diagnostic_and_no_candidates():
    retained, _, diagnostic = DiscoveryAgent._filter_candidate_rows_by_geography(
        rows=[("munich", 48.137, 11.575)],
        constraints={"location_region": "Bavaria"},
    )

    assert retained == []
    assert diagnostic == "region_bounds_unverified"
