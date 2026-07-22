"""
app/services/web_search.py — Tavily web search for supplier discovery.

WHY TAVILY (not Google/Bing directly)?
Tavily is built for AI agents:
- Returns clean text content (not raw HTML)
- Filters spam/SEO content automatically
- 1000 searches/month free (no credit card)
- Optimized for LLM context window (returns ~5KB per result)
"""

import logging
import math
import re
from collections.abc import Sequence
from functools import lru_cache
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger(__name__)

_CATEGORY_SEARCH_TERMS = {
    "tools_hardware": "hand tools industrial tools hardware",
    "office_supplies": "office furniture office supplies workplace equipment",
    "construction_materials": "construction materials building materials",
    "food_ingredients": "food ingredients",
    "software_services": "software services",
}


class WebSearchResult:
    """
    Normalized web search result.
    snippet = short text from Tavily
    full_content = full page text (populated lazily via page_fetcher)
    """

    def __init__(
        self,
        url: str,
        title: str,
        content: str,
        score: float = 0.0,
    ):
        self.url = url
        self.title = title
        self.snippet = content      # Tavily snippet
        self.full_content = None    # Populated on demand by page_fetcher
        self.score = score

    def __repr__(self) -> str:
        return f"<WebSearchResult title={self.title[:50]!r} url={self.url}>"


class WebSearchService:
    """Web search using Tavily, optimized for finding supplier websites."""

    def __init__(self) -> None:
        if not settings.TAVILY_API_KEY:
            logger.warning("TAVILY_API_KEY not set. External discovery will be disabled.")
            self._client = None
        else:
            # Availability marker. Calls use httpx directly so each query can
            # honor the remaining end-to-end request budget.
            self._client = object()
            logger.info("Web search service initialized (Tavily)")

    @property
    def is_available(self) -> bool:
        return self._client is not None

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _search_raw(
        self,
        query: str,
        max_results: int = 10,
        timeout_seconds: float | None = None,
    ) -> list[dict]:
        """Raw Tavily HTTP search call with retry and a call-level timeout."""
        if not self._client:
            return []
        timeout = max(0.1, float(timeout_seconds or settings.EXTERNAL_DISCOVERY_TIMEOUT))
        payload = {
            "api_key": settings.TAVILY_API_KEY,
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        with httpx.Client(timeout=timeout) as client:
            response = client.post(settings.TAVILY_API_BASE_URL, json=payload)
            response.raise_for_status()
            result = response.json()
        return result.get("results", [])

    def search_suppliers(
        self,
        category: str | None = None,
        industry_context: str | None = None,
        country: str | None = None,
        city: str | None = None,
        certifications: list[str] | None = None,
        product_terms: list[str] | None = None,
        raw_query: str | None = None,
        max_results: int = 10,
        timeout_seconds: float | None = None,
    ) -> list[WebSearchResult]:
        """
        Search the web for suppliers matching constraints.

        Constructs a targeted query like:
        "ISO 9001 certified metals supplier Germany manufacturing company"
        """
        if not self.is_available:
            logger.warning("[web_search] Tavily unavailable — skipping web discovery")
            return []

        target_results = max(1, max_results)
        queries = self._build_supplier_queries(
            category=category,
            industry_context=industry_context,
            country=country,
            city=city,
            certifications=certifications,
            product_terms=product_terms,
            raw_query=raw_query,
        )

        all_results: list[WebSearchResult] = []
        seen_urls: set[str] = set()
        per_query_limit = max(1, min(5, math.ceil(target_results / max(1, len(queries)))))

        for _family, query in queries:
            logger.info("[web_search] Searching: %r", query)

            try:
                raw = self._search_raw(
                    query,
                    max_results=per_query_limit,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as e:
                logger.error("[web_search] Tavily search failed for %r: %s", query, e)
                continue

            for r in raw:
                url = r.get("url", "")
                content = r.get("content", "")
                if not url or not content:
                    continue
                key = self._normalise_url(url)
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                all_results.append(
                    WebSearchResult(
                        url=url,
                        title=r.get("title", ""),
                        content=content,
                        score=float(r.get("score", 0.0)),
                    )
                )
        all_results.sort(key=lambda result: result.score, reverse=True)
        selected = all_results[:target_results]
        logger.info("[web_search] Found %d unique results", len(selected))
        return selected

    @classmethod
    def _build_supplier_queries(
        cls,
        *,
        category: str | None,
        industry_context: str | None,
        country: str | None,
        city: str | None,
        certifications: list[str] | None,
        product_terms: list[str] | None,
        raw_query: str | None,
    ) -> list[tuple[str, str]]:
        location = " ".join(cls._dedupe_terms([city, country]))
        cert_text = " ".join(cls._dedupe_terms(certifications or []))
        product_phrases = cls._compact_product_terms(product_terms or [])
        primary_product = product_phrases[0] if product_phrases else ""
        product_variants = product_phrases[1:]

        category_text = ""
        if category:
            category_text = _CATEGORY_SEARCH_TERMS.get(category, category.replace("_", " "))
        industry_text = " ".join(str(industry_context or "").replace("_", " ").split())
        context_text = industry_text or category_text

        query_parts: list[tuple[str, list[str]]] = []

        if primary_product and country and country.casefold() in {"germany", "deutschland"}:
            query_parts.append(("country_domain", [
                "site:.de",
                primary_product,
                context_text,
                location,
                "manufacturer supplier",
            ]))

        if primary_product:
            query_parts.append(("manufacturer", [
                primary_product,
                context_text,
                "manufacturer",
                location,
                "company",
            ]))
            distributor_product = product_variants[0] if product_variants else primary_product
            query_parts.append(("distributor", [
                distributor_product,
                "distributor wholesaler",
                location,
                "company",
            ]))
            if len(product_variants) > 1:
                query_parts.append(("wholesaler_variant", [
                    product_variants[1],
                    "wholesaler distributor",
                    location,
                    "company",
                ]))

        if certifications:
            query_parts.append(("certification", [
                cert_text,
                primary_product or context_text,
                "certified supplier",
                location,
            ]))

        if context_text:
            query_parts.append(("category", [
                context_text,
                primary_product,
                "supplier",
                location,
            ]))

        if not query_parts:
            query_parts.append(("fallback", [location, "supplier manufacturer company"]))

        queries: list[tuple[str, str]] = []
        seen: set[str] = set()
        for family, parts in query_parts:
            query = " ".join(p for p in parts if p).strip()
            query = " ".join(query.split())
            if not query or query.casefold() in seen:
                continue
            seen.add(query.casefold())
            queries.append((family, query))
        return queries

    @classmethod
    def _compact_product_terms(
        cls,
        values: Sequence[str | None],
        *,
        max_terms: int = 3,
    ) -> list[str]:
        """Keep an ordered primary phrase plus genuinely distinct variants."""
        selected: list[str] = []
        selected_tokens: list[set[str]] = []
        for cleaned in cls._dedupe_terms(values):
            tokens = set(re.findall(r"[\w+.-]+", cleaned.casefold()))
            if not tokens:
                continue
            if any(
                tokens <= existing or existing <= tokens
                for existing in selected_tokens
            ):
                continue
            selected.append(cleaned)
            selected_tokens.append(tokens)
            if len(selected) >= max(1, max_terms):
                break
        return selected

    @staticmethod
    def _dedupe_terms(values: Sequence[str | None]) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not value:
                continue
            cleaned = " ".join(str(value).strip().split())
            key = cleaned.casefold()
            if not cleaned or key in seen:
                continue
            seen.add(key)
            terms.append(cleaned)
        return terms

    @staticmethod
    def _normalise_url(url: str) -> str:
        parsed = urlparse(url)
        host = parsed.netloc.casefold().removeprefix("www.")
        path = (parsed.path or "/").rstrip("/") or "/"
        return f"{host}{path}"


@lru_cache(maxsize=1)
def get_web_search_service() -> WebSearchService:
    """Cached singleton instance of WebSearchService."""
    return WebSearchService()
