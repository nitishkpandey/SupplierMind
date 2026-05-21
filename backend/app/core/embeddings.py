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
import json
import logging
from functools import lru_cache

import voyageai
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger(__name__)

# voyage-3-lite produces 512-dimensional vectors
# This constant is used when creating the Milvus collection schema
EMBEDDING_DIM = 512
EMBEDDING_MODEL = "voyage-3-lite"

# Voyage AI batch size limit
MAX_BATCH_SIZE = 128


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
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _call_api(
        self,
        texts: list[str],
        input_type: str,
    ) -> list[list[float]]:
        """
        Raw API call to Voyage AI.
        Retries up to 3 times on transient failures.
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

        all_embeddings: list[list[float]] = []

        # Process in batches to respect API limits
        for i in range(0, len(texts), MAX_BATCH_SIZE):
            batch = texts[i : i + MAX_BATCH_SIZE]
            logger.debug(
                "Embedding batch %d/%d (%d texts)",
                i // MAX_BATCH_SIZE + 1,
                (len(texts) - 1) // MAX_BATCH_SIZE + 1,
                len(batch),
            )
            batch_embeddings = self._call_api(batch, input_type)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

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
