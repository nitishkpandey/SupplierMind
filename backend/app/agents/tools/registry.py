"""Tool registry pattern for the ReAct Parser (Task 3.1).

A Tool is a side-effect-free callable plus its self-description for the LLM
(name, prose description, JSON-schema for arguments). The ToolRegistry holds
tools by name and renders them into the system prompt the ReAct loop sees.

Design choices (see Yao et al. 2022, arXiv:2210.03629):
- Tools must be idempotent at the Parser stage (the Parser is *understanding*
  the query, not acting on the world). No DB writes, no external side effects.
- Tools may raise; the loop catches and surfaces the exception as an
  Observation with an `error` key so the LLM can recover or finish.
- The registry stays small (~5 tools). With many more tools the LLM's choice
  quality degrades faster than the value of adding them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Tool:
    """One tool the ReAct Parser may call.

    name           — identifier the LLM emits as the Action value.
    description    — one-sentence purpose, shown verbatim in the system prompt.
    args_schema    — JSON-schema-style dict describing the expected arguments.
                     Used only for the prompt; not enforced at runtime.
    fn             — the callable. Must accept the args by keyword and return
                     a JSON-serialisable Python value.
    """

    name: str
    description: str
    args_schema: dict
    fn: Callable[..., Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name!r}")
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def list_for_prompt(self) -> str:
        """Render the registered tools as a string the LLM can read."""
        lines: list[str] = []
        for tool in self._tools.values():
            lines.append(f"- {tool.name}: {tool.description}")
            lines.append(f"  arguments: {json.dumps(tool.args_schema)}")
        return "\n".join(lines)


def build_default_registry() -> ToolRegistry:
    """Wire the five standard Parser tools.

    Kept here (not in __init__) so callers that need an empty registry for
    tests can construct one without triggering the imports of every tool
    module (some pull in services that touch the network on import).
    """
    from app.agents.tools.geocode import geocode_location_tool
    from app.agents.tools.cert_taxonomy import canonicalize_certification_tool
    from app.agents.tools.industry_context import infer_industry_context_tool
    from app.agents.tools.quantity_parser import parse_quantity_unit_tool
    from app.agents.tools.past_query_stub import lookup_past_query_tool

    reg = ToolRegistry()
    reg.register(geocode_location_tool())
    reg.register(canonicalize_certification_tool())
    reg.register(infer_industry_context_tool())
    reg.register(parse_quantity_unit_tool())
    reg.register(lookup_past_query_tool())
    return reg
