"""Deterministic normalization and comparison for supplier capacity rates."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CapacityUnit:
    """A capacity unit expressed relative to a dimension's base unit per day."""

    canonical: str | None
    dimension: str
    scale: float
    period: str | None


_PERIOD_DAYS = {
    "day": 1.0,
    "week": 7.0,
    "month": 30.0,
    "year": 365.0,
}

_PERIOD_ALIASES = {
    "d": "day", "day": "day", "daily": "day",
    "wk": "week", "wks": "week", "week": "week", "weekly": "week",
    "mo": "month", "mos": "month", "month": "month", "monthly": "month",
    "yr": "year", "yrs": "year", "year": "year", "annum": "year", "annual": "year",
    "annually": "year", "yearly": "year",
}

_COUNT_ALIASES = {
    "u", "unit", "units", "piece", "pieces", "pc", "pcs", "item", "items",
}
_KG_ALIASES = {"kg", "kgs", "kilogram", "kilograms"}
_TON_ALIASES = {
    "t", "ton", "tons", "tonne", "tonnes", "metricton", "metrictons",
    "metrictonne", "metrictonnes",
}
_LITRE_ALIASES = {"l", "liter", "liters", "litre", "litres"}


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def normalise_capacity_unit(raw: str | None) -> CapacityUnit:
    """Normalize a capacity unit without guessing across dimensions.

    Product nouns such as ``housings/month`` are count capacities. Unknown
    strings without a recognizable unit remain unknown instead of being
    silently compared as counts.
    """
    if not raw or not str(raw).strip():
        return CapacityUnit(None, "unknown", 1.0, None)

    text = str(raw).strip().lower().replace("_", " ")
    text = re.sub(r"\s+per\s+", "/", text)
    parts = [part.strip() for part in text.split("/", 1)]
    unit_text = parts[0]
    period = None
    if len(parts) == 2:
        period = _PERIOD_ALIASES.get(_compact(parts[1]))
        if period is None:
            return CapacityUnit(None, "unknown", 1.0, None)

    compact_unit = _compact(unit_text)
    if compact_unit in _COUNT_ALIASES:
        base, dimension, scale = "units", "count", 1.0
    elif compact_unit in _KG_ALIASES:
        base, dimension, scale = "kg", "mass", 1.0
    elif compact_unit in _TON_ALIASES:
        base, dimension, scale = "metric_tons", "mass", 1000.0
    elif compact_unit in _LITRE_ALIASES:
        base, dimension, scale = "litres", "volume", 1.0
    elif period and re.search(r"[a-z]", compact_unit):
        # A named product followed by a rate period is a product count.
        base, dimension, scale = "units", "count", 1.0
    else:
        return CapacityUnit(None, "unknown", 1.0, period)

    canonical = f"{base}/{period}" if period else base
    return CapacityUnit(canonical, dimension, scale, period)


def _base_rate(value: float, unit: CapacityUnit) -> float:
    period_days = _PERIOD_DAYS.get(unit.period or "day", 1.0)
    return float(value) * unit.scale / period_days


def compare_capacity(
    actual_value: float | int | None,
    actual_unit: str | None,
    required_value: float | int | None,
    required_unit: str | None,
) -> tuple[str, str]:
    """Return PASS/PARTIAL/FAIL plus an evidence-friendly reason."""
    if actual_value is None:
        return "PARTIAL", "Capacity data not available in supplier profile"
    if required_value is None:
        return "PASS", "No minimum capacity value was required"

    actual = normalise_capacity_unit(actual_unit)
    required = normalise_capacity_unit(required_unit)
    if actual.canonical is None or required.canonical is None:
        return (
            "PARTIAL",
            f"Capacity units could not be verified: supplier={actual_unit or 'unknown'}, "
            f"required={required_unit or 'unknown'}",
        )
    if actual.dimension != required.dimension:
        return (
            "FAIL",
            f"Incompatible capacity dimensions: supplier={actual.dimension}, "
            f"required={required.dimension}",
        )

    actual_rate = _base_rate(float(actual_value), actual)
    required_rate = _base_rate(float(required_value), required)
    if actual_rate >= required_rate:
        return (
            "PASS",
            f"Capacity {float(actual_value):,.0f} {actual.canonical} meets minimum "
            f"{float(required_value):,.0f} {required.canonical}",
        )
    if actual_rate >= required_rate * 0.8:
        return (
            "PARTIAL",
            f"Capacity {float(actual_value):,.0f} {actual.canonical} is slightly below "
            f"minimum {float(required_value):,.0f} {required.canonical}",
        )
    return (
        "FAIL",
        f"Capacity {float(actual_value):,.0f} {actual.canonical} is below minimum "
        f"{float(required_value):,.0f} {required.canonical}",
    )
