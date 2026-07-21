"""Deterministic capacity-unit normalization and comparison regressions."""

from app.utils.capacity_units import compare_capacity, normalise_capacity_unit


def test_product_count_noun_becomes_units_per_month():
    assert normalise_capacity_unit("aluminum housings/month").canonical == "units/month"


def test_metric_tons_and_kg_are_compared_after_conversion():
    status, _ = compare_capacity(60, "metric_tons/month", 50_000, "kg/month")
    assert status == "PASS"


def test_count_and_mass_dimensions_fail():
    status, _ = compare_capacity(60_000, "kg/month", 50_000, "units/month")
    assert status == "FAIL"


def test_unknown_supplier_unit_is_partial():
    status, _ = compare_capacity(60_000, None, 50_000, "units/month")
    assert status == "PARTIAL"
