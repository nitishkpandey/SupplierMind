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
from functools import lru_cache
from typing import Optional
from urllib.parse import urlparse

from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger(__name__)

_CATEGORY_SEARCH_TERMS = {
    "tools_hardware": "hand tools industrial tools hardware",
    "office_supplies": "office supplies workplace equipment",
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
            from tavily import TavilyClient
            self._client = TavilyClient(api_key=settings.TAVILY_API_KEY)
            logger.info("Web search service initialized (Tavily)")

    @property
    def is_available(self) -> bool:
        return self._client is not None

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _search_raw(self, query: str, max_results: int = 10) -> list[dict]:
        """Raw Tavily search call with retry."""
        if not self._client:
            return []
        result = self._client.search(
            query=query,
            search_depth="advanced",
            max_results=max_results,
            include_answer=False,
            include_raw_content=False,
        )
        return result.get("results", [])

    def search_suppliers(
        self,
        category: Optional[str] = None,
        country: Optional[str] = None,
        city: Optional[str] = None,
        certifications: Optional[list[str]] = None,
        product_terms: Optional[list[str]] = None,
        raw_query: Optional[str] = None,
        max_results: int = 10,
    ) -> list[WebSearchResult]:
        """
        Search the web for suppliers matching constraints.

        Constructs a targeted query like:
        "ISO 9001 certified metals supplier Germany manufacturing company"
        """
        if not self.is_available:
            logger.warning("[web_search] Tavily unavailable — skipping web discovery")
            return []

        target_results = max(max_results, 10)
        queries = self._build_supplier_queries(
            category=category,
            country=country,
            city=city,
            certifications=certifications,
            product_terms=product_terms,
            raw_query=raw_query,
        )

        all_results: list[WebSearchResult] = []
        seen_urls: set[str] = set()
        per_query_limit = max(5, min(target_results, 10))

        for query in queries:
            logger.info("[web_search] Searching: %r", query)

            try:
                raw = self._search_raw(query, max_results=per_query_limit)
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
                if len(all_results) >= target_results:
                    logger.info("[web_search] Found %d unique results", len(all_results))
                    return all_results

        logger.info("[web_search] Found %d unique results", len(all_results))
        return all_results

    @classmethod
    def _build_supplier_queries(
        cls,
        *,
        category: Optional[str],
        country: Optional[str],
        city: Optional[str],
        certifications: Optional[list[str]],
        product_terms: Optional[list[str]],
        raw_query: Optional[str],
    ) -> list[str]:
        location = " ".join(cls._dedupe_terms([city, country]))
        cert_text = " ".join(cls._dedupe_terms(certifications or []))
        product_text = " ".join(cls._dedupe_terms(product_terms or [])[:6])

        category_text = ""
        if category:
            category_text = _CATEGORY_SEARCH_TERMS.get(category, category.replace("_", " "))

        query_parts: list[list[str]] = []

        if product_text and country and country.casefold() in {"germany", "deutschland"}:
            query_parts.append([
                "site:.de",
                product_text,
                category_text,
                "manufacturer supplier GmbH",
            ])
            query_parts.append([
                product_text,
                "German",
                category_text,
                "manufacturer official website GmbH",
            ])

        if product_text:
            query_parts.append([
                cert_text,
                product_text,
                category_text,
                "supplier manufacturer distributor",
                location,
                "company website",
            ])

        if certifications:
            query_parts.append([
                cert_text,
                product_text or category_text,
                "certified supplier manufacturer",
                location,
                "official website",
            ])

        if category:
            query_parts.append([
                category_text,
                "supplier manufacturer",
                location,
                "company website",
            ])

        if raw_query and product_text:
            query_parts.append([
                product_text,
                location,
                "manufacturer supplier official website",
            ])

        if not query_parts:
            query_parts.append([location, "supplier manufacturer company website"])

        queries: list[str] = []
        seen: set[str] = set()
        for parts in query_parts:
            query = " ".join(p for p in parts if p).strip()
            query = " ".join(query.split())
            if not query or query.casefold() in seen:
                continue
            seen.add(query.casefold())
            queries.append(query)
        return queries[:3]

    @staticmethod
    def _dedupe_terms(values: list[str | None]) -> list[str]:
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
