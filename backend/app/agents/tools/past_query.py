"""lookup_past_query — semantic recall over the user's prior queries (Task 3.2).

Replaces the empty-list stub from Task 3.1 with a real Milvus-backed search.
The implementation is a factory: callers construct a Tool by passing a
QueryMemoryService and the `current_user_id` for the request. The user_id is
closure-bound at factory time so the LLM physically cannot point the search
at another user's history, regardless of what it emits in `Action Input`.

This is the privacy-critical surface in Task 3.2 — see test_query_memory.py's
`test_lookup_tool_ignores_user_id_override_attempt` for the structural pin.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.tools.registry import Tool
from app.services.query_memory import QueryMemoryService

logger = logging.getLogger(__name__)

_DESCRIPTION = (
    "Search the current user's own past procurement queries by semantic "
    "similarity. Use when the query references prior context like 'same as "
    "last time', 'similar to before', or when the current query is ambiguous "
    "and prior history might disambiguate it. Returns past queries sorted by "
    "similarity (most similar first). Returns an empty list if no past "
    "queries match — that is not an error, it just means the user has no "
    "relevant history."
)

_ARGS_SCHEMA = {
    "type": "object",
    "properties": {
        "query_text": {
            "type": "string",
            "description": "Text to search past queries against.",
        },
        "top_k": {
            "type": "integer",
            "description": "How many past queries to return (max 5).",
            "default": 3,
        },
    },
    "required": ["query_text"],
}

_MAX_TOP_K = 5
# Tuned 2026-06-10 (Task 3.4) from a measured Voyage cosine distribution:
# related cross-domain paraphrases ("fabric" probe vs. textile seed queries)
# score 0.395-0.512 while unrelated industrial queries top out at 0.436.
# The original 0.65 (spec default) returned zero hits for every paraphrase
# tested; 0.45 keeps related recall while still rejecting unrelated pairs.
_DEFAULT_MIN_SIMILARITY = 0.45


def make_lookup_past_query_tool(
    memory_service: QueryMemoryService,
    current_user_id: str,
    min_similarity: float = _DEFAULT_MIN_SIMILARITY,
) -> Tool:
    """Build a `lookup_past_query` Tool scoped to one user's memory.

    The `current_user_id` is captured in the closure; any `user_id` kwarg
    emitted by the LLM is dropped before dispatch. Per-request Parser
    construction is what makes this safe — see
    `ParserAgent.build_for_user()`.
    """

    bound_user_id = str(current_user_id) if current_user_id else ""

    def lookup_past_query(query_text: str, top_k: int = 3, **_ignored: Any) -> Any:
        """The Tool's callable. **kwargs swallow any LLM-emitted `user_id`."""
        if not bound_user_id:
            # No user → no memory. Cleaner than raising; the LLM can move on.
            return []
        try:
            top_k = int(top_k or 3)
        except (TypeError, ValueError):
            top_k = 3
        top_k = max(1, min(top_k, _MAX_TOP_K))

        try:
            hits = memory_service.search(
                user_id=bound_user_id,
                query_text=query_text,
                top_k=top_k,
                min_similarity=min_similarity,
            )
        except Exception as e:  # noqa: BLE001 — memory failure must not crash the ReAct loop
            logger.warning(
                "[lookup_past_query] memory search failed for user=%s: %s",
                bound_user_id,
                e,
            )
            return {
                "error": "memory_unavailable",
                "detail": f"{type(e).__name__}: {e}",
                "results": [],
            }
        return hits

    return Tool(
        name="lookup_past_query",
        description=_DESCRIPTION,
        args_schema=_ARGS_SCHEMA,
        fn=lookup_past_query,
    )
