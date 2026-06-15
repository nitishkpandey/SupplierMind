"""lookup_past_query — stub bridge to Task 3.2's semantic long-term memory.

Returns an empty list today. Task 3.2 will replace the implementation with a
Milvus semantic search over the user's prior parsed queries. The Tool's name,
description, and arg shape are stable so that the ReAct prompt does not need
to change when 3.2 lands.
"""

from __future__ import annotations

from typing import Any

from app.agents.tools.registry import Tool

_DESCRIPTION = (
    "Find semantically-similar past queries from this user's history. Use when "
    "the current query is ambiguous and prior queries might disambiguate, or "
    "when it references context like 'same as last time'. (Stub — returns an "
    "empty list until semantic memory lands in Task 3.2.)"
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
    # Argument validation kept loose; Task 3.2 will tighten with real input.
    _ = (query_text or "").strip(), int(top_k or 0)
    return []


def lookup_past_query_tool() -> Tool:
    return Tool(
        name="lookup_past_query",
        description=_DESCRIPTION,
        args_schema=_ARGS_SCHEMA,
        fn=_run,
    )
