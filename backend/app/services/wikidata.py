"""
app/services/wikidata.py — Wikidata SPARQL for company enrichment.

WHY WIKIDATA?
- Completely free, no API key, no rate limits (within fair use)
- Has structured data on millions of companies worldwide
- Provides: headquarters location, industry, founding year, website
"""

import logging
from functools import lru_cache
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger(__name__)


class WikidataService:
    """Look up companies in Wikidata via SPARQL."""

    def __init__(self) -> None:
        self._sparql_endpoint = settings.WIKIDATA_SPARQL_ENDPOINT
        self._headers = {
            "User-Agent": settings.NOMINATIM_USER_AGENT,
            "Accept": "application/json",
        }

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=False,
    )
    def lookup_company(self, name: str) -> Optional[dict]:
        """
        Look up a company in Wikidata.
        Returns enrichment data or None if not found.
        """
        sparql_query = f"""
        SELECT ?company ?companyLabel ?country ?countryLabel ?industry ?industryLabel ?founded ?website
        WHERE {{
          ?company rdfs:label "{name}"@en .
          ?company wdt:P31/wdt:P279* wd:Q4830453 .
          OPTIONAL {{ ?company wdt:P17 ?country . }}
          OPTIONAL {{ ?company wdt:P452 ?industry . }}
          OPTIONAL {{ ?company wdt:P571 ?founded . }}
          OPTIONAL {{ ?company wdt:P856 ?website . }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }}
        LIMIT 1
        """

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    self._sparql_endpoint,
                    params={"query": sparql_query, "format": "json"},
                    headers=self._headers,
                )

            if response.status_code != 200:
                return None

            data = response.json()
            bindings = data.get("results", {}).get("bindings", [])
            if not bindings:
                return None

            row = bindings[0]

            def value(field: str) -> Optional[str]:
                return row.get(field, {}).get("value")

            return {
                "wikidata_id": (value("company") or "").split("/")[-1],
                "country": value("countryLabel"),
                "industry": value("industryLabel"),
                "founded": value("founded"),
                "website": value("website"),
                "source": "wikidata",
            }

        except Exception as e:
            logger.debug("[wikidata] Lookup failed for %r: %s", name, e)
            return None


@lru_cache(maxsize=1)
def get_wikidata_service() -> WikidataService:
    return WikidataService()
