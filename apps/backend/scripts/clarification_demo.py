"""Drive the Task 3.3 killer demo: multi-turn clarification dialogue.

Three turns against the live Groq LLM. No database, no Milvus, no API —
the Parser is exercised directly so the demo runs even when the rest of
the stack is offline. Each turn appends the user's prior answers to the
raw query (mirroring `resume_pipeline`'s augmentation) and re-runs the
Parser; the previous turn's parsed_constraints are threaded through as a
hint via state["previous_partial_constraints"].

  Turn 1: "I need suppliers for our project"
          → Parser raises Rule-1 clarification (missing product, no memory)
  Turn 2: User answers "packaging materials" → re-run Parser.
          With product known, Rule 1 stays quiet; sparse constraints
          and/or low confidence may still trip Rule 2 → second question.
  Turn 3: User answers "anywhere in EU with ISO 9001" → re-run Parser.
          Now product + cert + region → state == complete.

Output: demo_output/week_3_agentic/clarification_demo.json
with three turn blocks (raw query, parsed_constraints, react_trace,
clarification flags) and a verification dict.

Usage:
    uv run python scripts/clarification_demo.py
"""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.parser_agent import ParserAgent  # noqa: E402
from app.agents.tools import build_default_registry  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
)
logger = logging.getLogger("clarification_demo")

OUT_DIR = (
    Path(__file__).resolve().parents[2]
    / "demo_output"
    / "week_3_agentic"
)
OUT_PATH = OUT_DIR / "clarification_demo.json"

TURNS = [
    "I need suppliers for our project",
    "packaging materials",
    "anywhere in EU with ISO 9001",
]


def _run_parser(
    raw_query: str,
    turn_number: int,
    previous_partial: dict | None = None,
) -> dict:
    """Run the Parser end-to-end; return its output + the surface fields the
    demo notes consume."""
    registry = build_default_registry()
    parser = ParserAgent(tool_registry=registry)
    state = {
        "raw_query": raw_query,
        "query_id": f"demo-clarify-t{turn_number}-{int(time.time())}",
        "user_id": "",  # skip user-memory loading
        "audit_log": [],
        "search_scope": "approved_only",
        "turn_number": turn_number,
        "previous_partial_constraints": previous_partial,
    }
    start = time.time()
    out = parser.execute(state)
    elapsed_ms = int((time.time() - start) * 1000)
    audit_entries = out.get("audit_log") or []
    clarification_entries = [
        e for e in audit_entries
        if e.get("agent_name") == "clarification_handler"
    ]
    return {
        "raw_query": raw_query,
        "turn_number": turn_number,
        "elapsed_ms": elapsed_ms,
        "terminated_by": out.get("react_terminated_by"),
        "iterations": len(out.get("react_trace") or []),
        "tools_called": [
            s["action"]
            for s in out.get("react_trace") or []
            if s.get("action") and s["action"] != "Finish"
        ],
        "needs_clarification": bool(out.get("needs_clarification")),
        "clarification_question": out.get("clarification_question"),
        "parsed_constraints": out.get("parsed_constraints"),
        "react_trace": out.get("react_trace"),
        "audit_entries": [
            {
                "agent_name": e.get("agent_name"),
                "action": e.get("action"),
                "duration_ms": e.get("duration_ms"),
                "output_summary": e.get("output_summary", "")[:300],
            }
            for e in audit_entries
        ],
        "clarification_handler_entries": clarification_entries,
    }


def _augmented_query(history: list[tuple[str, str]], current: str) -> str:
    """Glue the running dialogue together the same way `resume_pipeline`
    augments the original prompt on the backend."""
    parts = [history[0][0] if history else current]
    if history:
        for _question, answer in history:
            parts.append(f"User clarification: {answer}")
        # The current message is the next user answer.
        parts.append(f"User clarification: {current}")
    return "\n\n".join(parts) if history else current


def _verify(turns: list[dict]) -> dict:
    """Compute the assertions Component D listed for this demo."""
    t1, t2, t3 = turns
    return {
        "turn1_raised_clarification": t1["needs_clarification"] is True,
        "turn1_question_mentions_product": (
            "product" in (t1["clarification_question"] or "").lower()
        ),
        "turn2_progress_or_complete": (
            (t2["parsed_constraints"] or {}).get("product_type") is not None
        ),
        "turn3_state_complete": t3["needs_clarification"] is False,
        "turn3_has_certification": bool(
            (t3["parsed_constraints"] or {}).get("certifications")
        ),
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    demo_id = str(uuid.uuid4())[:8]

    print(f"\n== Clarification Dialogue Demo (id={demo_id}) ==")

    # ── Turn 1 — ambiguous opening ────────────────────────────────────
    print("\nTurn 1 — opening")
    t1 = _run_parser(TURNS[0], turn_number=1, previous_partial=None)
    print(
        f"  needs_clarification={t1['needs_clarification']} "
        f"question={t1['clarification_question']!r}"
    )

    # ── Turn 2 — user provides product ────────────────────────────────
    # Mirror resume_pipeline: append the user's answer to the raw query
    # and thread the prior partial constraints into the Parser.
    turn2_query = f"{TURNS[0]}\n\nUser clarification: {TURNS[1]}"
    print("\nTurn 2 — user supplies product")
    t2 = _run_parser(
        turn2_query,
        turn_number=2,
        previous_partial=t1.get("parsed_constraints"),
    )
    print(
        f"  needs_clarification={t2['needs_clarification']} "
        f"product={t2['parsed_constraints'].get('product_type')!r} "
        f"question={t2['clarification_question']!r}"
    )

    # ── Turn 3 — user provides geography + cert ───────────────────────
    turn3_query = (
        f"{TURNS[0]}\n\n"
        f"User clarification: {TURNS[1]}\n\n"
        f"User clarification: {TURNS[2]}"
    )
    print("\nTurn 3 — user supplies geography + cert")
    t3 = _run_parser(
        turn3_query,
        turn_number=3,
        previous_partial=t2.get("parsed_constraints"),
    )
    print(
        f"  needs_clarification={t3['needs_clarification']} "
        f"final_constraints={json.dumps(t3['parsed_constraints'], default=str)[:200]}..."
    )

    verification = _verify([t1, t2, t3])

    payload = {
        "demo_id": demo_id,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "turns": [t1, t2, t3],
        "verification": verification,
    }
    OUT_PATH.write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nSaved: {OUT_PATH}")
    print(json.dumps(verification, indent=2))


if __name__ == "__main__":
    main()
