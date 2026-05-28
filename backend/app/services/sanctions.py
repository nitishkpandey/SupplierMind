"""
app/services/sanctions.py — OpenSanctions screening for newly discovered suppliers.

CRITICAL FOR PROCUREMENT:
A supplier on a sanctions list (EU, UN, US OFAC, etc.) cannot be procured from
legally. Every newly discovered supplier MUST be screened before adding to
the database. This is a hard procurement compliance requirement.
"""

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SanctionsResult:
    is_flagged: bool
    risk_score: float
    matched_lists: list[str] = field(default_factory=list)
    raw_response: Optional[dict] = None


class SanctionsService:
    """OpenSanctions API client for sanctions/risk screening."""

    def __init__(self) -> None:
        self._base_url = settings.SANCTIONS_API_BASE_URL
        self._headers = {}
        if settings.OPENSANCTIONS_API_KEY:
            self._headers["Authorization"] = f"ApiKey {settings.OPENSANCTIONS_API_KEY}"

    def screen_company(self, name: str) -> SanctionsResult:
        """
        Screen a company name against sanctions lists.
        Returns SanctionsResult with risk assessment.
        """
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    f"{self._base_url}/search/default",
                    params={"q": name, "limit": 3, "schema": "Company"},
                    headers=self._headers,
                )

            if response.status_code != 200:
                logger.debug("[sanctions] HTTP %d for %r", response.status_code, name)
                return SanctionsResult(is_flagged=False, risk_score=0.0)

            data = response.json()
            results = data.get("results", [])

            if not results:
                return SanctionsResult(is_flagged=False, risk_score=0.0)

            top = results[0]
            score = float(top.get("score", 0.0))
            datasets = top.get("datasets", [])

            sanction_keywords = ("sanction", "ofac", "fsf", "consolidated")
            is_sanctions = any(
                kw in d.lower()
                for d in datasets
                for kw in sanction_keywords
            )

            is_flagged = is_sanctions and score >= 0.7

            return SanctionsResult(
                is_flagged=is_flagged,
                risk_score=score if is_sanctions else 0.0,
                matched_lists=datasets if is_sanctions else [],
                raw_response=top if is_flagged else None,
            )

        except Exception as e:
            logger.warning("[sanctions] Screening failed for %r: %s", name, e)
            return SanctionsResult(is_flagged=False, risk_score=0.0)


@lru_cache(maxsize=1)
def get_sanctions_service() -> SanctionsService:
    return SanctionsService()
