"""Semantic long-term memory for past procurement queries (Task 3.2).

Each successful query (Evaluator verdict == accepted/auto_accept) is embedded
with Voyage and persisted to a Milvus collection alongside its parsed
constraints. The Parser's ReAct loop calls `lookup_past_query` on subsequent
queries to retrieve semantically-similar prior queries belonging to the SAME
user, letting the agent stitch context across turns (e.g. "same product as
last time but in Bavaria").

Privacy boundaries — three layers of defence:

1. The `user_id` is closure-bound at tool factory time (`make_lookup_past_query_tool`
   in app/agents/tools/past_query.py); the LLM cannot pass another user's id.
2. `search()` always pushes a `user_id == "..."` expression to Milvus;
   even a bug above this layer cannot cross-talk users.
3. `delete_all_for_user()` enables right-to-be-forgotten via DELETE
   /api/v1/users/me/memory.

Design choices:

- Cosine similarity (Voyage embeddings are unit-norm).
- HNSW index for the embedding; scalar index for fast user_id filtering.
- VARCHAR for parsed_constraints_json — Milvus 2.4-and-earlier has no JSON
  column type; the service serialises on write and parses on read.
- The collection is created lazily on first access; tests pass a unique
  collection name to isolate from the production collection.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Iterable, Optional

from app.core.config import settings
from app.core.embeddings import EMBEDDING_DIM, EmbeddingClient, get_embedding_client

logger = logging.getLogger(__name__)

# Production collection name. Tests pass a unique name to keep their rows
# out of the production collection.
COLLECTION_NAME = "query_memory"

# Voyage embeddings are 512-dim, so the vector field width matches.
_QUERY_TEXT_MAX = 2000
_CONSTRAINTS_JSON_MAX = 8000


def _connect_milvus_if_needed() -> None:
    """Establish a default Milvus connection if no alias exists yet.

    The supplier vector store (`MilvusVectorStore`) usually beats us to it at
    app startup, but the test suite and the demo driver may import the memory
    service before the supplier store has been created — so we connect on
    demand. This is a no-op when the connection already exists.
    """
    from pymilvus import connections

    # pymilvus 2.4 has `has_connection(alias)` returning bool. Older versions
    # only expose `list_connections()` returning [(alias, addr), ...].
    have_connection = False
    if hasattr(connections, "has_connection"):
        try:
            have_connection = bool(connections.has_connection("default"))
        except Exception:
            have_connection = False
    else:
        try:
            have_connection = any(
                alias == "default" for alias, _ in connections.list_connections()
            )
        except Exception:
            have_connection = False

    if have_connection:
        return

    connections.connect(
        alias="default",
        host=settings.MILVUS_HOST,
        port=settings.MILVUS_PORT,
    )
    logger.info(
        "[query_memory] Connected to Milvus at %s:%d",
        settings.MILVUS_HOST,
        settings.MILVUS_PORT,
    )


def ensure_collection_exists(name: str = COLLECTION_NAME):
    """Return the `query_memory` collection, creating it if absent.

    Idempotent. Safe to call from every QueryMemoryService instance.
    """
    from pymilvus import (
        Collection,
        CollectionSchema,
        DataType,
        FieldSchema,
        utility,
    )

    _connect_milvus_if_needed()

    if utility.has_collection(name):
        collection = Collection(name)
        try:
            collection.load()
        except Exception as e:  # noqa: BLE001 — already-loaded is fine
            logger.debug("[query_memory] Collection load no-op: %s", e)
        return collection

    fields = [
        FieldSchema(
            name="memory_id",
            dtype=DataType.VARCHAR,
            max_length=64,
            is_primary=True,
        ),
        FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(
            name="query_text",
            dtype=DataType.VARCHAR,
            max_length=_QUERY_TEXT_MAX,
        ),
        FieldSchema(
            name="parsed_constraints_json",
            dtype=DataType.VARCHAR,
            max_length=_CONSTRAINTS_JSON_MAX,
        ),
        FieldSchema(name="created_at_ts", dtype=DataType.INT64),
        FieldSchema(
            name="embedding",
            dtype=DataType.FLOAT_VECTOR,
            dim=EMBEDDING_DIM,
        ),
    ]
    schema = CollectionSchema(
        fields=fields,
        description="Per-user query memory for semantic recall (Task 3.2)",
    )
    collection = Collection(name=name, schema=schema)

    collection.create_index(
        field_name="embedding",
        index_params={
            "metric_type": "COSINE",
            "index_type": "HNSW",
            "params": {"M": 16, "efConstruction": 200},
        },
    )
    # Scalar index on user_id keeps the privacy filter cheap as the row count
    # grows. The expression `user_id == "..."` planner-rewrites to an index
    # probe instead of a brute-force scan over the entire collection.
    try:
        collection.create_index(field_name="user_id", index_name="user_id_idx")
    except Exception as e:  # noqa: BLE001 — some Milvus builds reject scalar indexes
        logger.warning(
            "[query_memory] Scalar index on user_id not created (%s); "
            "filter will still work, just slower at very large scale.",
            e,
        )
    collection.load()
    logger.info("[query_memory] Created Milvus collection: %s", name)
    return collection


class QueryMemoryService:
    """Persistence + retrieval for the Parser's long-term memory."""

    def __init__(
        self,
        embedding_client: Optional[EmbeddingClient] = None,
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        self._embeddings = embedding_client or get_embedding_client()
        self._collection_name = collection_name
        self._collection = ensure_collection_exists(collection_name)

    # ── Write ──────────────────────────────────────────────────────────

    def write(
        self,
        user_id: str,
        query_text: str,
        parsed_constraints: dict,
    ) -> str:
        """Persist a successful query for future semantic recall.

        Returns the assigned memory_id (uuid4). Caller is responsible for
        deciding *when* to write (we only persist evaluator-accepted runs).
        """
        if not user_id:
            raise ValueError("user_id is required for memory write")
        if not query_text:
            raise ValueError("query_text is required for memory write")

        memory_id = str(uuid.uuid4())
        embedding = self._embeddings.embed_one(query_text, input_type="query")

        constraints_json = json.dumps(parsed_constraints or {}, default=str)
        if len(constraints_json) > _CONSTRAINTS_JSON_MAX - 200:
            logger.warning(
                "[query_memory] parsed_constraints_json truncated for memory_id=%s "
                "(was %d chars)",
                memory_id,
                len(constraints_json),
            )
            constraints_json = constraints_json[: _CONSTRAINTS_JSON_MAX - 200]

        clipped_query = query_text[:_QUERY_TEXT_MAX]
        created_at = int(time.time())

        self._collection.insert(
            [
                [memory_id],
                [str(user_id)],
                [clipped_query],
                [constraints_json],
                [created_at],
                [embedding],
            ]
        )
        # Flush is synchronous — the row is queryable as soon as this returns.
        # That matters for the killer demo (Q1 → write → Q2 within seconds).
        self._collection.flush()
        return memory_id

    # ── Read ───────────────────────────────────────────────────────────

    def search(
        self,
        user_id: str,
        query_text: str,
        top_k: int = 3,
        min_similarity: float = 0.65,
    ) -> list[dict[str, Any]]:
        """Return top-k semantically similar past queries for THIS user only.

        `min_similarity` filters out distant matches before they reach the
        LLM. The Parser's ReAct loop receives an empty list when no past
        query crosses the threshold, which the tool description tells it is
        not an error.
        """
        if not user_id:
            return []
        if not query_text:
            return []

        embedding = self._embeddings.embed_one(query_text, input_type="query")
        top_k = max(1, min(int(top_k or 3), 5))

        results = self._collection.search(
            data=[embedding],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"ef": 64}},
            limit=top_k,
            expr=f'user_id == "{_escape_for_expr(str(user_id))}"',
            output_fields=[
                "query_text",
                "parsed_constraints_json",
                "created_at_ts",
            ],
        )

        if not results or len(results) == 0:
            return []

        hits: list[dict[str, Any]] = []
        for hit in results[0]:
            score = float(hit.score)
            if score < min_similarity:
                continue
            constraints_raw = hit.entity.get("parsed_constraints_json") or "{}"
            try:
                constraints = json.loads(constraints_raw)
            except json.JSONDecodeError:
                logger.warning(
                    "[query_memory] Skipping memory with un-deserialisable "
                    "parsed_constraints_json"
                )
                continue
            hits.append(
                {
                    "query": hit.entity.get("query_text"),
                    "constraints": constraints,
                    "timestamp": hit.entity.get("created_at_ts"),
                    "similarity": score,
                }
            )
        return hits

    # ── Delete (GDPR) ───────────────────────────────────────────────────

    def delete_all_for_user(self, user_id: str) -> int:
        """Remove every memory row owned by `user_id`. Returns row count deleted.

        Backs the DELETE /api/v1/users/me/memory endpoint. Right-to-be-forgotten.
        """
        if not user_id:
            return 0
        expr = f'user_id == "{_escape_for_expr(str(user_id))}"'
        result = self._collection.delete(expr)
        self._collection.flush()
        # pymilvus returns either an int-like or a MutationResult — accept both.
        count = getattr(result, "delete_count", None)
        if count is None:
            count = int(result) if result is not None else 0
        return int(count)

    # ── Test helpers ────────────────────────────────────────────────────

    def _reset_for_tests(self) -> None:
        """Wipe every row in the collection. Tests only."""
        self._collection.delete("memory_id != ''")
        self._collection.flush()


def _escape_for_expr(value: str) -> str:
    """Defend the Milvus expression from injection via user_id strings.

    user_id is a UUID in production so this is belt-and-braces, but the public
    contract accepts a string and we never want to give a future maintainer a
    foot-gun.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


# ── Module-level singleton (built lazily on first request) ─────────────

_memory_service_singleton: Optional[QueryMemoryService] = None


def get_memory_service() -> QueryMemoryService:
    """Return the process-wide QueryMemoryService.

    Constructed on first access — Milvus must already be reachable when this
    is called. Each web request reuses the same instance (and therefore the
    same warm collection handle) which is what we want.
    """
    global _memory_service_singleton
    if _memory_service_singleton is None:
        _memory_service_singleton = QueryMemoryService()
    return _memory_service_singleton


def reset_memory_service_singleton() -> None:
    """For tests that need to inject a different embedding client."""
    global _memory_service_singleton
    _memory_service_singleton = None


def iter_audit_friendly(hits: Iterable[dict]) -> list[dict]:
    """Trim a memory hits list down to the safe-to-log subset.

    Used by the orchestrator / API audit flush; we keep the query text and
    similarity score but drop the full constraints blob to keep audit rows
    compact.
    """
    return [
        {"query": h.get("query"), "similarity": h.get("similarity")}
        for h in hits or []
    ]
