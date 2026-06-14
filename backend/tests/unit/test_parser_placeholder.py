"""Phase E Step 1 — Rule 1 placeholder pollution.

Two parser-quality guards (pure, no LLM):
  - product_type: contentless placeholder phrases must not survive as a product.
  - location_country: generic procurement nouns ("suppliers", "manufacturers",
    ...) are never valid countries and must be dropped (the Q8 v2 flake:
    "Food ingredient SUPPLIERS ..." mis-parsed "suppliers" as a country).
"""

import pytest

from app.agents.parser_agent import ParserAgent, _is_placeholder_product


# ── product_type placeholder phrases (must be rejected) ──────────────
@pytest.mark.parametrize("phrase", [
    "our project", "our needs", "my project", "my needs",
    "the requirement", "this requirement", "your supplier", "the task",
    # obvious variants
    "this task", "that project", "the tasks", "our new project",
])
def test_placeholder_phrases_rejected(phrase):
    assert _is_placeholder_product(phrase) is True


# ── real product types (must still match) ────────────────────────────
@pytest.mark.parametrize("product", [
    "metals", "electronics", "logistics", "textiles", "chemicals",
    "packaging materials", "industrial valves", "food ingredients",
])
def test_real_product_types_not_placeholder(product):
    assert _is_placeholder_product(product) is False


# ── location_country procurement-noun guard ──────────────────────────
def _parser() -> ParserAgent:
    return ParserAgent.__new__(ParserAgent)


@pytest.mark.parametrize("noun", [
    "suppliers", "supplier", "manufacturers", "manufacturer",
    "vendors", "vendor", "providers", "provider", "Suppliers", "VENDOR",
])
def test_procurement_noun_not_a_country(noun):
    out = _parser()._normalise_constraints(
        {"product_type": "valves", "location_country": noun}, trace=[]
    )
    assert out["location_country"] is None


@pytest.mark.parametrize("country", ["Germany", "France", "India", "United States"])
def test_real_country_preserved(country):
    out = _parser()._normalise_constraints(
        {"product_type": "valves", "location_country": country}, trace=[]
    )
    assert out["location_country"] == country
