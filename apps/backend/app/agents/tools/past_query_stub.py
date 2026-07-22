"""No-op lookup_past_query fallback.

Production parser runs use app.agents.tools.past_query with user-scoped Milvus
memory. This fallback is used only by tests or degraded parser construction
when memory initialization is unavailable.
"""

from __future__ import annotations

from typing import Any

from app.agents.tools.registry import Tool

# Deliberately NOT imported from past_query.py: that module pulls in
# query_memory (Milvus/Voyage clients) at import time, and this stub exists
# precisely so callers can build a registry without those imports. The
# description also intentionally differs (it admits the degraded behaviour).
_DESCRIPTION = (
    "Find semantically-similar past queries from this user's history. Use when "
    "the current query is ambiguous and prior queries might disambiguate, or "
    "when it references context like 'same as last time'. In this degraded "
    "fallback registry it returns an empty list."
)

_ARGS_SCHEMA = {
    "type": "object",
    "properties": {
        "query_text": {"type": "string", "description": "Current raw query text."},
        "top_k": {"type": "integer", "description": "Maximum past queries to return.", "default": 3},
    },
    "required": ["query_text"],
}


def _run(query_text: str, top_k: int = 3) -> list[dict[str, Any]]:
    _ = (query_text or "").strip(), int(top_k or 0)
    return []


def lookup_past_query_tool() -> Tool:
    return Tool(
        name="lookup_past_query",
        description=_DESCRIPTION,
        args_schema=_ARGS_SCHEMA,
        fn=_run,
    )
