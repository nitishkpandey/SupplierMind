"""Shared cleanup for optional text extracted from external sources."""

import re
from typing import Iterable

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
