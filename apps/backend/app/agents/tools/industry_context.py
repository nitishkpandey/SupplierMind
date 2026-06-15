"""infer_industry_context tool — small LLM call mapping product to industry."""

from __future__ import annotations

import json
from typing import Any

from app.agents.tools.registry import Tool
from app.core.llm import LLMClient, get_llm_client

_DESCRIPTION = (
    "Infer the industry context for a product description: industry name, certs "
    "commonly required in that industry, and typical capacity units. Use to "
    "raise hidden expectations the query did not state explicitly."
)

_ARGS_SCHEMA = {
    "type": "object",
    "properties": {
        "product_description": {
            "type": "string",
            "description": "Free-form product or service description, e.g. 'aerospace machined parts'."
        }
    },
    "required": ["product_description"],
}

_SYSTEM = (
    "You are an industry taxonomist for procurement. Given a product description, "
    "return JSON with three fields:\n"
    "  industry        — one short industry name (e.g. 'aerospace', 'food processing')\n"
    "  common_certs    — list of certifications commonly required in that industry\n"
    "  typical_units   — typical capacity unit used in that industry (e.g. 'units/month', 'tons/year')\n"
    "Return ONLY valid JSON. No prose."
)


def _run(product_description: str, *, _llm: LLMClient | None = None) -> dict[str, Any]:
    text = (product_description or "").strip()
    if not text:
        return {"industry": None, "common_certs": [], "typical_units": None}

    llm = _llm or get_llm_client()
    raw = llm.complete_json(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Product: {text}"},
        ],
        max_tokens=256,
        temperature=0.0,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"industry": None, "common_certs": [], "typical_units": None, "raw": raw[:200]}
    return {
        "industry": data.get("industry"),
        "common_certs": list(data.get("common_certs") or []),
        "typical_units": data.get("typical_units"),
    }


def infer_industry_context_tool(*, _llm: LLMClient | None = None) -> Tool:
    def _fn(product_description: str) -> dict[str, Any]:
        return _run(product_description, _llm=_llm)

    return Tool(
        name="infer_industry_context",
        description=_DESCRIPTION,
        args_schema=_ARGS_SCHEMA,
        fn=_fn,
    )
