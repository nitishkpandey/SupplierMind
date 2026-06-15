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

from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger(__name__)


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

        parts = []
        if certifications:
            parts.append(" ".join(certifications))
        if category:
            cat_term = category.replace("_", " ")
            parts.append(f"{cat_term} supplier manufacturer")
        if city:
            parts.append(city)
        if country:
            parts.append(country)
        parts.append("company website")

        query = " ".join(parts).strip()
        logger.info("[web_search] Searching: %r", query)

        try:
            raw = self._search_raw(query, max_results=max_results)
            results = [
                WebSearchResult(
                    url=r.get("url", ""),
                    title=r.get("title", ""),
                    content=r.get("content", ""),
                    score=float(r.get("score", 0.0)),
                )
                for r in raw
                if r.get("url") and r.get("content")
            ]
            logger.info("[web_search] Found %d results", len(results))
            return results

        except Exception as e:
            logger.error("[web_search] Tavily search failed: %s", e)
            return []


@lru_cache(maxsize=1)
def get_web_search_service() -> WebSearchService:
    """Cached singleton instance of WebSearchService."""
    return WebSearchService()
