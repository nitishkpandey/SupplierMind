"""
app/core/vector_store.py — Vector store abstraction (Milvus + ChromaDB fallback).

WHY AN ABSTRACTION LAYER?
Milvus requires Docker with ~4GB RAM.
ChromaDB needs only pip install and 256MB RAM.

Both provide the same functionality: store embeddings and search by similarity.
The abstraction means agents call vector_store.search() and don't know
(or care) whether Milvus or ChromaDB is running underneath.

MILVUS CONCEPTS:
- Collection = a table in a relational DB
- Entity = a row
- Vector field = the 512-float embedding
- Index = pre-built structure for fast similarity search (HNSW)
- HNSW = Hierarchical Navigable Small World — excellent recall + speed tradeoff
- COSINE = similarity metric (1.0 = identical, 0.0 = unrelated)

HOW SEARCH WORKS:
1. Convert query text to a 512-float vector
2. Ask Milvus: "Find the 20 entities whose vectors are closest to this vector"
3. Returns supplier_ids in order of relevance
4. Discovery Agent looks up those suppliers in PostgreSQL
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.core.embeddings import EMBEDDING_DIM, get_embedding_client

logger = logging.getLogger(__name__)

COLLECTION_NAME = "suppliers"


@dataclass
class SearchResult:
    """One result from a vector similarity search."""
    supplier_id: str          # UUID string of the supplier in PostgreSQL
    similarity_score: float   # 0.0 to 1.0 (1.0 = identical)
    distance: float           # Raw distance metric from Milvus/ChromaDB


class BaseVectorStore(ABC):
    """Abstract interface — same API for Milvus and ChromaDB."""

    @abstractmethod
    def add_suppliers(self, suppliers: list[dict]) -> list[str]:
        """
        Embed and index a list of suppliers.

        Args:
            suppliers: List of supplier dicts (must have 'id', 'name', 'description', etc.)

        Returns:
            List of vector IDs (stored back in supplier.embedding_id)
        """
        ...

    @abstractmethod
    def search(self, query_text: str, top_k: int = 20) -> list[SearchResult]:
        """
        Search for suppliers semantically similar to query_text.

        Args:
            query_text: The procurement query or description to search for
            top_k: Number of results to return

        Returns:
            List of SearchResult ordered by similarity (highest first)
        """
        ...

    @abstractmethod
    def delete_supplier(self, supplier_id: str) -> None:
        """Remove a supplier's embedding from the vector store."""
        ...

    @abstractmethod
    def count(self) -> int:
        """Return the number of indexed suppliers."""
        ...


class MilvusVectorStore(BaseVectorStore):
    """
    Milvus vector store implementation.
    Creates the collection and HNSW index if they don't exist yet.
    """

    def __init__(self) -> None:
        from pymilvus import (
            Collection,
            CollectionSchema,
            DataType,
            FieldSchema,
            connections,
            utility,
        )

        self._Collection = Collection
        self._utility = utility
        self._DataType = DataType

        # Connect to Milvus
        connections.connect(
            alias="default",
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
        )
        logger.info(
            "Connected to Milvus at %s:%d", settings.MILVUS_HOST, settings.MILVUS_PORT
        )

        # Create collection if it doesn't exist
        if not utility.has_collection(COLLECTION_NAME):
            self._create_collection()
            logger.info("Created Milvus collection: %s", COLLECTION_NAME)
        else:
            logger.info("Using existing Milvus collection: %s", COLLECTION_NAME)

        self._collection = Collection(COLLECTION_NAME)
        self._collection.load()

    def _create_collection(self) -> None:
        """
        Define the schema for the suppliers collection.

        Fields:
        - pk: Auto-incrementing integer primary key (required by Milvus)
        - supplier_id: Our PostgreSQL UUID (varchar, what we actually use)
        - embedding: The 512-float vector
        """
        from pymilvus import Collection, CollectionSchema, FieldSchema

        fields = [
            FieldSchema(
                name="pk",
                dtype=self._DataType.INT64,
                is_primary=True,
                auto_id=True,
            ),
            FieldSchema(
                name="supplier_id",
                dtype=self._DataType.VARCHAR,
                max_length=36,  # UUID string length
            ),
            FieldSchema(
                name="embedding",
                dtype=self._DataType.FLOAT_VECTOR,
                dim=EMBEDDING_DIM,  # 512 for voyage-3-lite
            ),
        ]
        schema = CollectionSchema(
            fields=fields,
            description="Supplier description embeddings for semantic search",
        )
        collection = Collection(name=COLLECTION_NAME, schema=schema)

        # HNSW index — best recall/speed tradeoff for our dataset size
        # M=16: graph connectivity (higher = better recall, more memory)
        # efConstruction=256: build-time search depth (higher = better quality index)
        collection.create_index(
            "embedding",
            {
                "metric_type": "COSINE",
                "index_type": "HNSW",
                "params": {"M": 16, "efConstruction": 256},
            },
        )

    def add_suppliers(self, suppliers: list[dict]) -> list[str]:
        """Embed suppliers and insert into Milvus collection."""
        if not suppliers:
            return []

        embed_client = get_embedding_client()

        # Build embedding texts
        texts = [embed_client.embed_supplier_text(s) for s in suppliers]

        # Generate embeddings in batch (efficient)
        logger.info("Generating embeddings for %d suppliers...", len(suppliers))
        embeddings = embed_client.embed_batch(texts, input_type="document")

        # Insert into Milvus
        supplier_ids = [str(s["id"]) for s in suppliers]
        data = [supplier_ids, embeddings]
        self._collection.insert(data)
        self._collection.flush()  # Ensure data is persisted

        logger.info("Indexed %d suppliers in Milvus", len(suppliers))
        # Return supplier_ids as embedding IDs (we'll store these in PostgreSQL)
        return supplier_ids

    def search(self, query_text: str, top_k: int = 20) -> list[SearchResult]:
        """Search for semantically similar suppliers."""
        embed_client = get_embedding_client()

        # Use "query" input type for search (different from "document")
        query_vector = embed_client.embed_one(query_text, input_type="query")

        search_params = {
            "metric_type": "COSINE",
            "params": {"ef": 128},  # ef > top_k for better recall
        }

        results = self._collection.search(
            data=[query_vector],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            output_fields=["supplier_id"],
        )

        search_results = []
        for hit in results[0]:
            search_results.append(
                SearchResult(
                    supplier_id=hit.entity.get("supplier_id"),
                    similarity_score=float(hit.score),
                    distance=float(hit.distance),
                )
            )

        return search_results

    def delete_supplier(self, supplier_id: str) -> None:
        """Remove supplier's vector from Milvus."""
        self._collection.delete(f'supplier_id == "{supplier_id}"')
        self._collection.flush()

    def count(self) -> int:
        """Return number of indexed entities."""
        return self._collection.num_entities


class ChromaVectorStore(BaseVectorStore):
    """
    ChromaDB fallback — used when LITE_MODE=true or Milvus is unavailable.
    Identical interface, no Docker required.
    """

    def __init__(self) -> None:
        import chromadb

        self._client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_PATH)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "Using ChromaDB (LITE_MODE) at path: %s", settings.CHROMA_PERSIST_PATH
        )

    def add_suppliers(self, suppliers: list[dict]) -> list[str]:
        """Add suppliers to ChromaDB."""
        if not suppliers:
            return []

        embed_client = get_embedding_client()
        texts = [embed_client.embed_supplier_text(s) for s in suppliers]
        embeddings = embed_client.embed_batch(texts, input_type="document")
        supplier_ids = [str(s["id"]) for s in suppliers]

        self._collection.add(
            ids=supplier_ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=[{"supplier_id": sid} for sid in supplier_ids],
        )
        logger.info("Indexed %d suppliers in ChromaDB", len(suppliers))
        return supplier_ids

    def search(self, query_text: str, top_k: int = 20) -> list[SearchResult]:
        """Search ChromaDB by vector similarity."""
        embed_client = get_embedding_client()
        query_vector = embed_client.embed_one(query_text, input_type="query")

        results = self._collection.query(
            query_embeddings=[query_vector],
            n_results=min(top_k, self._collection.count()),
            include=["distances", "metadatas"],
        )

        search_results = []
        if results["ids"] and results["ids"][0]:
            for i, supplier_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i]
                # ChromaDB returns cosine distance (0=identical, 2=opposite)
                # Convert to similarity score (1=identical, 0=unrelated)
                similarity = 1.0 - (distance / 2.0)
                search_results.append(
                    SearchResult(
                        supplier_id=supplier_id,
                        similarity_score=similarity,
                        distance=distance,
                    )
                )

        return search_results

    def delete_supplier(self, supplier_id: str) -> None:
        self._collection.delete(ids=[supplier_id])

    def count(self) -> int:
        return self._collection.count()


# Module-level instance (set during app startup)
_vector_store_instance: BaseVectorStore | None = None


def set_vector_store_instance(vs: BaseVectorStore) -> None:
    global _vector_store_instance
    _vector_store_instance = vs


def get_vector_store() -> BaseVectorStore:
    if _vector_store_instance is None:
        raise RuntimeError("Vector store not initialized. Check app startup.")
    return _vector_store_instance


def create_vector_store() -> BaseVectorStore:
    """
    Factory function — creates the appropriate vector store based on settings.
    Called once during app startup.
    """
    provider = settings.effective_vector_db
    logger.info("Initializing vector store: %s", provider)
    if provider == "milvus":
        return MilvusVectorStore()
    else:
        return ChromaVectorStore()
