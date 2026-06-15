"""canonicalize_certification tool — wraps Task 1.3 cert taxonomy lookup."""

from __future__ import annotations

from typing import Any

from app.agents.tools.registry import Tool

_DESCRIPTION = (
    "Resolve a free-form certification name (e.g. 'ISO 9001:2015', 'AS9100D', "
    "'OEKO-TEX 100') to its canonical taxonomy key and report what other certs "
    "it supersedes. Use when the query mentions a cert that may have variants "
    "so downstream compliance checks compare apples to apples."
)

_ARGS_SCHEMA = {
    "type": "object",
    "properties": {
        "cert_name": {
            "type": "string",
            "description": "Cert name as written by the user, e.g. 'ISO9001' or 'IATF16949:2016'."
        }
    },
    "required": ["cert_name"],
}


def _run(cert_name: str) -> dict[str, Any]:
    # Local import keeps the registry importable without pulling LLM modules in.
    from app.agents.compliance_agent import CERT_TAXONOMY, canonical_cert_key

    name = (cert_name or "").strip()
    if not name:
        return {"resolved": False, "reason": "empty cert_name"}

    key = canonical_cert_key(name)
    if key is None:
        return {
            "resolved": False,
            "input": name,
            "reason": "no canonical match in taxonomy",
        }

    entry = CERT_TAXONOMY.get(key, {})
    return {
        "resolved": True,
        "input": name,
        "canonical": key,
        "category": entry.get("category"),
        "full_name": entry.get("full_name"),
        "supersedes": list(entry.get("contains_or_supersedes") or []),
        "not_equivalent_to": list(entry.get("NOT_equivalent_to") or []),
        "common_in_industries": list(entry.get("common_in_industries") or []),
    }


def canonicalize_certification_tool() -> Tool:
    return Tool(
        name="canonicalize_certification",
        description=_DESCRIPTION,
        args_schema=_ARGS_SCHEMA,
        fn=_run,
    )
