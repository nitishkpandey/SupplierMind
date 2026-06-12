"""parse_quantity_unit tool — deterministic regex-based quantity + unit parsing."""

from __future__ import annotations

import re
from typing import Any

from app.agents.tools.registry import Tool

_DESCRIPTION = (
    "Parse a quantity + unit string into a normalised numeric value and unit. "
    "Handles SI multipliers like 10k or 2.5M and per-period suffixes like "
    "units/month, tons/year. Use for capacity and lead-time phrases. "
    "No LLM call; purely deterministic."
)

_ARGS_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "Free-form quantity phrase, e.g. '10k units/month' or '500 kg'."
        }
    },
    "required": ["text"],
}

_MULTIPLIERS = {
    "k": 1_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
}

# Strip thousands-separator commas (3-digit groups) before parsing so
# "1,200" becomes "1200" and "10,000.5" becomes "10000.5". A bare comma
# followed by 1–2 digits is treated as the decimal separator (European).
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}(\D|$))")
_DECIMAL_COMMA_RE = re.compile(r"(?<=\d),(?=\d{1,2}(\D|$))")

# Captures: <number><optional SI multiplier><optional unit-phrase>
# The multiplier (k/M/b) must be followed by whitespace, '/', or end —
# otherwise 'kg' would parse as '× 1000' + 'g'.
_RE = re.compile(
    r"""
    ^\s*
    (?P<value>\d+(?:\.\d+)?)                  # 10, 10.5
    \s*
    (?P<mult>[kKmMbB])?(?=\s|/|$)             # k / M / b — guarded by lookahead
    \s*
    (?P<unit>[A-Za-z/][A-Za-z\s/.-]*)?        # units/month, kg, tons / year
    \s*$
    """,
    re.VERBOSE,
)


def _normalise_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    u = unit.strip().lower()
    # "units per month" → "units/month" before whitespace is stripped, so the
    # natural-language form collapses to the same canonical key as "units/mo".
    u = re.sub(r"\s+per\s+", "/", u)
    u = re.sub(r"\s+", "", u).strip(".")
    aliases = {
        "u/mo": "units/month",
        "u/month": "units/month",
        "units/mo": "units/month",
        "u/yr": "units/year",
        "u/year": "units/year",
        "t/yr": "tons/year",
        "tons/yr": "tons/year",
        "kg": "kg",
        "kgs": "kg",
        "kilograms": "kg",
    }
    return aliases.get(u, u or None)


def _run(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {"parsed": False, "reason": "empty text"}

    # Normalise commas: thousands-separator stripped, decimal-comma → dot.
    normalised = _THOUSANDS_RE.sub("", raw)
    normalised = _DECIMAL_COMMA_RE.sub(".", normalised)

    m = _RE.match(normalised)
    if not m:
        return {"parsed": False, "input": raw, "reason": "no numeric value matched"}

    try:
        value = float(m.group("value"))
    except ValueError:
        return {"parsed": False, "input": raw, "reason": f"unparsable number {m.group('value')!r}"}

    mult_char = (m.group("mult") or "").lower()
    multiplier = _MULTIPLIERS.get(mult_char, 1)
    value *= multiplier
    if value.is_integer():
        value = float(int(value))

    unit_raw = m.group("unit") or None
    if unit_raw:
        unit_raw = unit_raw.strip()
    normalised_unit = _normalise_unit(unit_raw)

    return {
        "parsed": True,
        "input": raw,
        "value": value,
        "unit": unit_raw,
        "normalized_unit": normalised_unit,
    }


def parse_quantity_unit_tool() -> Tool:
    return Tool(
        name="parse_quantity_unit",
        description=_DESCRIPTION,
        args_schema=_ARGS_SCHEMA,
        fn=_run,
    )
