"""One monotonic execution budget shared by every agent in a query."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping


class QueryDeadlineExceeded(RuntimeError):
    """Raised when continuing work would exceed the query execution budget."""


def remaining_seconds(
    state: Mapping[str, object],
    reserve: float = 0.0,
    *,
    monotonic: Callable[[], float] = time.monotonic,
) -> float:
    """Return usable seconds before the query deadline, excluding ``reserve``."""
    raw_deadline = state.get("deadline_at")
    if raw_deadline is None:
        raise QueryDeadlineExceeded("Query deadline is missing")
    remaining = float(raw_deadline) - monotonic() - max(0.0, float(reserve))
    if remaining <= 0:
        raise QueryDeadlineExceeded("Query execution deadline exceeded")
    return remaining
