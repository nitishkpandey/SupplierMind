"""app/agents/audit_log.py — single canonical audit-log entry writer.

Every agent (and the orchestrator's free-function finalize node) appends audit
entries through `append_audit_entry`, so the entry shape and the
state["audit_log"] initialisation live in exactly one place. Extracted from the
logic that was duplicated across base.py, parser_agent.py and orchestrator.py
(Audit B, groups 2 & 3). Output is byte-identical to the former call sites:
same keys, same order, snapshots appended only when provided.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def append_audit_entry(
    state: dict[str, Any],
    *,
    agent_name: str,
    action: str,
    input_summary: str,
    output_summary: str,
    duration_ms: int,
    reasoning: str | None = None,
    input_snapshot: dict | None = None,
    output_snapshot: dict | None = None,
) -> dict[str, Any]:
    """Build one audit entry and append it to ``state["audit_log"]``.

    The entry's keys and order match what the three former call sites built
    (agent_name, action, reasoning, input_summary, output_summary, duration_ms,
    timestamp). Optional input/output snapshots are added only when provided,
    matching base.py's richer entries. ``state["audit_log"]`` is initialised to
    an empty list when missing or None. Returns the entry for convenience.
    """
    entry: dict[str, Any] = {
        "agent_name": agent_name,
        "action": action,
        "reasoning": reasoning,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "duration_ms": duration_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if input_snapshot is not None:
        entry["input_snapshot"] = input_snapshot
    if output_snapshot is not None:
        entry["output_snapshot"] = output_snapshot

    if "audit_log" not in state or state["audit_log"] is None:
        state["audit_log"] = []
    state["audit_log"].append(entry)
    return entry
