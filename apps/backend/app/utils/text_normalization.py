"""Shared cleanup for optional text extracted from external sources."""

import re
from collections.abc import Iterable

NULL_TEXT_VALUES = {
    "",
    "-",
    "n/a",
    "na",
    "nil",
    "none",
    "null",
    "not applicable",
    "not available",
    "not specified",
    "unknown",
}

_SUPPLIER_LEGAL_SUFFIX_RE = re.compile(
    r"\b(?:gmbh|ag|kg|ug|ohg|ltd|limited|inc|llc|plc|corp|corporation|"
    r"company|co|sarl|s\.?a\.?|b\.?v\.?|n\.?v\.?|group|holding|holdings)\b",
    re.IGNORECASE,
)
_SUPPLIER_JOINER_RE = re.compile(r"\b(?:and|und)\b|&", re.IGNORECASE)


def clean_optional_text(value) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if text.casefold() in NULL_TEXT_VALUES:
        return None
    return text


def clean_text_list(values: Iterable | None) -> list[str]:
    if not values:
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_optional_text(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def normalise_supplier_name_for_dedupe(name: str) -> str:
    """Normalize company names enough to catch legal-suffix duplicates."""
    text = (name or "").casefold().replace(".", " ")
    text = _SUPPLIER_JOINER_RE.sub(" ", text)
    text = _SUPPLIER_LEGAL_SUFFIX_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())
