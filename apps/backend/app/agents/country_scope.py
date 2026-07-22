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
    return " ".join(strip_accents(value).casefold().split())


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
    """Return true when an interactive product-plus-country query needs local scope."""
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
