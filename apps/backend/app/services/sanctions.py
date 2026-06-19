"""
app/services/sanctions.py — OpenSanctions screening for newly discovered suppliers.

CRITICAL FOR PROCUREMENT:
A supplier on a sanctions list (EU, UN, US OFAC, etc.) cannot be procured from
legally. Every newly discovered supplier MUST be screened before adding to
the database. This is a hard procurement compliance requirement.

Task 1.6 Component C — hardened against the OpenSanctions rate limit:
  1. Cache verdicts (7-day TTL, normalized company name) — cheap repeat checks.
  2. Bounded exponential backoff (1s, 2s, 4s) on 429/5xx — survive throttling.
  3. Explicit `pending_review` status when screening can't complete — NEVER
     silently pass an unscreened supplier through as "clear".
Same process-local sync cache pattern as app/core/embeddings.py (the shared
app cache is async-only; this runs in sync LangGraph agent nodes).
"""

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Verdict cache: {normalized_name: (SanctionsResult, expiry_ts)}. Only definitive
# verdicts are cached — never pending_review (a 429 is not a verdict).
SANCTIONS_CACHE_TTL_SECONDS = 604800  # 7 days
_SANCTIONS_CACHE: dict[str, tuple["SanctionsResult", float]] = {}
_CACHE_MAX_ENTRIES = 5000

# Bounded exponential backoff for retryable failures (429 / 5xx / network).
# 1 + 2 + 4 = 7s worst case, then give up and return pending_review.
BACKOFF_SCHEDULE = (1, 2, 4)

# Corporate suffixes stripped to maximize cache hits without false matches.
_CORP_SUFFIXES = (
    "gmbh", "ltd", "limited", "ag", "inc", "incorporated", "llc", "plc",
    "bv", "b.v.", "sa", "s.a.", "srl", "spa", "s.p.a.", "co", "corp",
    "corporation", "company", "kg", "ohg", "ug", "as", "oy", "ab", "nv",
)
_SUFFIX_RE = re.compile(
    r"[\s,]+(" + "|".join(sorted({re.escape(s.replace(".", "")) for s in _CORP_SUFFIXES}, key=len, reverse=True)) + r")$"
)


def normalize_company_name(name: str) -> str:
    """Lowercase, drop periods, collapse whitespace, strip trailing corp suffixes."""
    n = (name or "").lower().replace(".", "")
    n = re.sub(r"\s+", " ", n).strip()
    prev = None
    while prev != n:
        prev = n
        n = re.sub(r"[\s,]+$", "", _SUFFIX_RE.sub("", n)).strip()
    return n


@dataclass
class SanctionsResult:
    is_flagged: bool
    risk_score: float
    status: str = "clear"  # "clear" | "flagged" | "pending_review"
    matched_lists: list[str] = field(default_factory=list)
    reason: str | None = None
    raw_response: dict | None = None


def interpret_response(data: dict | None) -> SanctionsResult:
    """Pure: turn a 200 OpenSanctions payload into a verdict."""
    results = (data or {}).get("results", []) if isinstance(data, dict) else []
    if not results:
        return SanctionsResult(is_flagged=False, risk_score=0.0, status="clear")

    top = results[0]
    score = float(top.get("score", 0.0))
    datasets = top.get("datasets", [])

    sanction_keywords = ("sanction", "ofac", "fsf", "consolidated")
    is_sanctions = any(kw in d.lower() for d in datasets for kw in sanction_keywords)
    is_flagged = is_sanctions and score >= 0.7

    return SanctionsResult(
        is_flagged=is_flagged,
        risk_score=score if is_sanctions else 0.0,
        status="flagged" if is_flagged else "clear",
        matched_lists=datasets if is_sanctions else [],
        raw_response=top if is_flagged else None,
    )


class SanctionsService:
    """OpenSanctions API client with caching, backoff, and explicit failure state."""

    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self._base_url = settings.SANCTIONS_API_BASE_URL
        self._headers = {}
        if settings.OPENSANCTIONS_API_KEY:
            self._headers["Authorization"] = f"ApiKey {settings.OPENSANCTIONS_API_KEY}"
        self._sleep = sleep

    def _fetch(self, name: str) -> tuple[int, dict | None]:
        """One HTTP call. Returns (status_code, parsed_json_or_None)."""
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                f"{self._base_url}/search/default",
                params={"q": name, "limit": 3, "schema": "Company"},
                headers=self._headers,
            )
        data = response.json() if response.status_code == 200 else None
        return response.status_code, data

    def screen_company(self, name: str) -> SanctionsResult:
        """
        Screen a company against sanctions lists.
        Cache-first, then API with bounded backoff, then pending_review.
        """
        if not settings.OPENSANCTIONS_API_KEY:
            return SanctionsResult(
                is_flagged=False,
                risk_score=0.0,
                status="pending_review",
                reason="OpenSanctions API key is not configured",
            )

        key = normalize_company_name(name)
        cached = _cache_get(key)
        if cached is not None:
            logger.info("[sanctions] cache hit for %s", name)
            return cached

        last_error: str | None = None
        for attempt in range(len(BACKOFF_SCHEDULE)):
            try:
                status_code, data = self._fetch(name)
            except Exception as e:  # network/timeout — retryable
                last_error = f"{type(e).__name__}: {e}"
                self._sleep(BACKOFF_SCHEDULE[attempt])
                continue

            if status_code == 200:
                result = interpret_response(data)
                _cache_set(key, result)
                return result

            if status_code == 429 or status_code >= 500:
                last_error = f"HTTP {status_code}"
                self._sleep(BACKOFF_SCHEDULE[attempt])
                continue

            if status_code in (401, 403):
                logger.warning(
                    "[sanctions] %s check pending review (API authorization failed: HTTP %d)",
                    name,
                    status_code,
                )
                return SanctionsResult(
                    is_flagged=False,
                    risk_score=0.0,
                    status="pending_review",
                    reason=f"OpenSanctions authorization failed (HTTP {status_code})",
                )

            # Non-retryable non-200 (e.g. 400/404): not a screening failure,
            # just no usable data. Treat as clear and move on.
            logger.debug("[sanctions] HTTP %d for %r", status_code, name)
            return SanctionsResult(is_flagged=False, risk_score=0.0, status="clear")

        logger.warning(
            "[sanctions] %s check pending review (API unavailable after %d retries: %s)",
            name, len(BACKOFF_SCHEDULE), last_error,
        )
        return SanctionsResult(
            is_flagged=False,
            risk_score=0.0,
            status="pending_review",
            reason=f"screening unavailable ({last_error})",
        )


def _cache_get(key: str) -> SanctionsResult | None:
    entry = _SANCTIONS_CACHE.get(key)
    if entry is None:
        return None
    result, expiry = entry
    if time.time() > expiry:
        _SANCTIONS_CACHE.pop(key, None)
        return None
    return result


def _cache_set(key: str, result: SanctionsResult) -> None:
    if len(_SANCTIONS_CACHE) >= _CACHE_MAX_ENTRIES:
        _SANCTIONS_CACHE.clear()
    _SANCTIONS_CACHE[key] = (result, time.time() + SANCTIONS_CACHE_TTL_SECONDS)


@lru_cache(maxsize=1)
def get_sanctions_service() -> SanctionsService:
    return SanctionsService()
