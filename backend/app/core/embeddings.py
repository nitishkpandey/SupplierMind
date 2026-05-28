"""
app/core/embeddings.py — Voyage AI embedding client.

Converts text into dense vector representations (embeddings).
Used by:
  - Ingestion pipeline: embed supplier descriptions → store in Milvus
  - Discovery Agent: embed query → search Milvus for similar suppliers

CACHING STRATEGY:
Embedding the same text twice costs API tokens and time.
We cache embeddings in Redis with a long TTL (7 days).
Supplier descriptions rarely change, so cache hits will be very high.
"""

import hashlib
import logging
import time
from functools import lru_cache

import voyageai
from voyageai.error import RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

# voyage-3-lite produces 512-dimensional vectors
# This constant is used when creating the Milvus collection schema
EMBEDDING_DIM = 512
EMBEDDING_MODEL = "voyage-3-lite"

# Voyage AI batch size limit
MAX_BATCH_SIZE = 128

# Embedding cache TTL — supplier descriptions and queries rarely change.
EMBED_CACHE_TTL_SECONDS = 604800  # 7 days
_EMBED_CACHE_MAX_ENTRIES = 5000

# Module-level sync cache: {cache_key: (vector, expiry_timestamp)}.
# The shared app cache (app.core.cache) is async-only; the embedding client is
# called from sync LangGraph agent nodes, so we keep a process-local sync cache
# here — same pattern as app/services/page_fetcher.py. This is what stops the
# discovery agent from re-embedding the identical query on every relaxation
# retry and blowing through Voyage's free-tier 3 RPM limit.
_EMBED_CACHE: dict[str, tuple[list[float], float]] = {}


class EmbeddingClient:
    """
    Wrapper around Voyage AI embeddings API.

    USAGE:
        from app.core.embeddings import get_embedding_client
        client = get_embedding_client()

        # Single text
        vector = client.embed_one("Steel manufacturer in Germany")

        # Batch (more efficient, fewer API calls)
        vectors = client.embed_batch(["text1", "text2", "text3"])
    """

    def __init__(self) -> None:
        if not settings.VOYAGE_API_KEY:
            raise ValueError(
                "VOYAGE_API_KEY is not set. "
                "Get your free key at https://dash.voyageai.com"
            )
        self._client = voyageai.Client(api_key=settings.VOYAGE_API_KEY)
        logger.info(
            "Embedding client initialized (provider=voyage, model=%s, dim=%d)",
            EMBEDDING_MODEL,
            EMBEDDING_DIM,
        )

    def _cache_key(self, text: str, input_type: str) -> str:
        """
        Create a unique cache key for a text + input_type combination.
        Uses MD5 hash so very long texts produce short keys.
        """
        content = f"{EMBEDDING_MODEL}:{input_type}:{text}"
        return f"embed:{hashlib.md5(content.encode()).hexdigest()}"

    @retry(
        retry=retry_if_exception_type(RateLimitError),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=4, min=4, max=30),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _call_api(
        self,
        texts: list[str],
        input_type: str,
    ) -> list[list[float]]:
        """
        Raw API call to Voyage AI.

        Retries specifically on RateLimitError with a long backoff. The free
        tier allows only 3 requests/minute, so a 1-second retry is pointless —
        waits ramp up to 30s to actually clear the rolling window.
        """
        result = self._client.embed(
            texts,
            model=EMBEDDING_MODEL,
            input_type=input_type,
        )
        return result.embeddings

    def embed_batch(
        self,
        texts: list[str],
        input_type: str = "document",
    ) -> list[list[float]]:
        """
        Embed a list of texts as documents (for indexing suppliers).

        input_type="document" → optimized for indexing
        input_type="query"    → optimized for search queries

        Automatically splits into batches if len(texts) > MAX_BATCH_SIZE.

        Args:
            texts: List of text strings to embed
            input_type: "document" or "query"

        Returns:
            List of embedding vectors, one per input text
        """
        if not texts:
            return []

        # Resolve from cache first; only call the API for misses.
        results: list[list[float] | None] = [None] * len(texts)
        miss_indices: list[int] = []
        miss_texts: list[str] = []
        for idx, text in enumerate(texts):
            cached = self._cache_get(text, input_type)
            if cached is not None:
                results[idx] = cached
            else:
                miss_indices.append(idx)
                miss_texts.append(text)

        if miss_texts:
            logger.debug(
                "Embedding %d/%d texts (rest served from cache)",
                len(miss_texts), len(texts),
            )
            fresh: list[list[float]] = []
            for i in range(0, len(miss_texts), MAX_BATCH_SIZE):
                batch = miss_texts[i : i + MAX_BATCH_SIZE]
                fresh.extend(self._call_api(batch, input_type))

            for idx, text, vector in zip(miss_indices, miss_texts, fresh):
                results[idx] = vector
                self._cache_set(text, input_type, vector)

        return [v for v in results if v is not None]

    def _cache_get(self, text: str, input_type: str) -> list[float] | None:
        entry = _EMBED_CACHE.get(self._cache_key(text, input_type))
        if entry is None:
            return None
        vector, expiry = entry
        if time.time() > expiry:
            _EMBED_CACHE.pop(self._cache_key(text, input_type), None)
            return None
        return vector

    def _cache_set(self, text: str, input_type: str, vector: list[float]) -> None:
        # Cap cache size to prevent unbounded memory growth.
        if len(_EMBED_CACHE) >= _EMBED_CACHE_MAX_ENTRIES:
            _EMBED_CACHE.clear()
        _EMBED_CACHE[self._cache_key(text, input_type)] = (
            vector,
            time.time() + EMBED_CACHE_TTL_SECONDS,
        )

    def embed_one(
        self,
        text: str,
        input_type: str = "document",
    ) -> list[float]:
        """
        Embed a single text. Convenience wrapper around embed_batch.

        Use input_type="query" when embedding a user's search query.
        Use input_type="document" when embedding supplier descriptions.
        """
        results = self.embed_batch([text], input_type=input_type)
        return results[0]

    def embed_supplier_text(self, supplier: dict) -> str:
        """
        Build the text representation of a supplier for embedding.

        WHY NOT JUST EMBED THE DESCRIPTION?
        The supplier's name, category, country, and certifications
        are also semantically meaningful. Concatenating them gives
        the embedding model more signal to work with.

        This exact format must be consistent between indexing and querying.
        If you change this format, you MUST re-index all suppliers.
        """
        parts = [
            supplier.get("name", ""),
            supplier.get("description", ""),
            f"Category: {supplier.get('category', '')}",
            f"Country: {supplier.get('country', '')}",
            f"City: {supplier.get('city', '')}",
            f"Certifications: {', '.join(supplier.get('certifications', []))}",
        ]
        return " | ".join(p for p in parts if p.strip())


@lru_cache(maxsize=1)
def get_embedding_client() -> EmbeddingClient:
    """Returns cached embedding client instance."""
    return EmbeddingClient()
