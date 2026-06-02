"""Tool registry and individual tools for the ReAct-based Parser agent (Task 3.1).

Each tool is registered with a name, an LLM-readable description, a JSON-schema
for its arguments, and a side-effect-free callable. The Parser's ReAct loop
selects tools from the registry based on the current query state.

Public entry points:
    from app.agents.tools import build_default_registry, Tool, ToolRegistry
"""

from app.agents.tools.registry import Tool, ToolRegistry, build_default_registry

__all__ = ["Tool", "ToolRegistry", "build_default_registry"]
