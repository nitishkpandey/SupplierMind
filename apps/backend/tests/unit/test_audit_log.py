"""Unit tests for the canonical audit-log writer (app/agents/audit_log.py)."""
from datetime import datetime

from app.agents.audit_log import append_audit_entry


def _kwargs(**over):
    base = dict(
        agent_name="parser",
        action="parse",
        input_summary="in",
        output_summary="out",
        duration_ms=12,
    )
    base.update(over)
    return base


def test_writes_correct_dict_shape():
    state: dict = {}
    entry = append_audit_entry(state, reasoning="why", **_kwargs())
    assert entry == {
        "agent_name": "parser",
        "action": "parse",
        "reasoning": "why",
        "input_summary": "in",
        "output_summary": "out",
        "duration_ms": 12,
        "timestamp": entry["timestamp"],  # value asserted separately below
    }
    # key order preserved (byte-identical to the former call sites)
    assert list(entry.keys()) == [
        "agent_name", "action", "reasoning", "input_summary",
        "output_summary", "duration_ms", "timestamp",
    ]


def test_initialises_list_when_audit_log_is_none():
    state: dict = {"audit_log": None}
    append_audit_entry(state, **_kwargs())
    assert isinstance(state["audit_log"], list)
    assert len(state["audit_log"]) == 1


def test_initialises_list_when_audit_log_absent():
    state: dict = {}
    append_audit_entry(state, **_kwargs())
    assert state["audit_log"] and len(state["audit_log"]) == 1


def test_appends_rather_than_overwrites():
    state: dict = {}
    append_audit_entry(state, action="first", **{k: v for k, v in _kwargs().items() if k != "action"})
    append_audit_entry(state, action="second", **{k: v for k, v in _kwargs().items() if k != "action"})
    assert [e["action"] for e in state["audit_log"]] == ["first", "second"]


def test_timestamp_is_timezone_aware_utc():
    state: dict = {}
    entry = append_audit_entry(state, **_kwargs())
    ts = datetime.fromisoformat(entry["timestamp"])
    assert ts.tzinfo is not None  # not naive
    assert ts.utcoffset().total_seconds() == 0  # UTC


def test_reasoning_defaults_to_none():
    state: dict = {}
    entry = append_audit_entry(state, **_kwargs())
    assert entry["reasoning"] is None


def test_snapshots_added_only_when_provided():
    state: dict = {}
    plain = append_audit_entry(state, **_kwargs())
    assert "input_snapshot" not in plain and "output_snapshot" not in plain

    rich = append_audit_entry(
        state, input_snapshot={"a": 1}, output_snapshot={"b": 2}, **_kwargs()
    )
    assert rich["input_snapshot"] == {"a": 1}
    assert rich["output_snapshot"] == {"b": 2}
