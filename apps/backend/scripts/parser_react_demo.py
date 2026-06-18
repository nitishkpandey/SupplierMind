"""Drive the ReAct ParserAgent against the configured live LLM and capture a trace.

Used for Task 3.1 evidence: prints a real trace + latency for the consolidated
writeup. Bypasses the API layer so it does not require the long-running uvicorn
process to be restarted before measurement.

Usage:
    uv run python scripts/parser_react_demo.py "<query>"

Writes:
    demo_output/week_3_agentic/parser_react_demo.json
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.parser_agent import ParserAgent  # noqa: E402

OUT_DIR = (
    Path(__file__).resolve().parents[2]
    / "demo_output"
    / "week_3_agentic"
)
DEFAULT_QUERIES = [
    "ISO 9001 certified packaging supplier in Germany",
    "AS9100 aerospace machining 10k units/month Bavaria",
    "Bronze supplier within 25km of Bremen ISO 9001 certified",
]


def _run_once(parser: ParserAgent, raw_query: str) -> dict:
    state = {
        "raw_query": raw_query,
        "query_id": f"demo-{int(time.time() * 1000)}",
        "user_id": "",  # skip memory loading
        "audit_log": [],
        "search_scope": "approved_only",
    }
    start = time.time()
    out = parser.execute(state)
    elapsed_ms = int((time.time() - start) * 1000)
    audit_entry = (out.get("audit_log") or [{}])[0]
    return {
        "raw_query": raw_query,
        "elapsed_ms": elapsed_ms,
        "terminated_by": out.get("react_terminated_by"),
        "iterations": len(out.get("react_trace") or []),
        "tools_called": [
            s["action"]
            for s in out.get("react_trace") or []
            if s.get("action") and s["action"] != "Finish"
        ],
        "parsed_constraints": out.get("parsed_constraints"),
        "needs_clarification": out.get("needs_clarification"),
        "react_trace": out.get("react_trace"),
        "audit_entry": {
            "action": audit_entry.get("action"),
            "duration_ms": audit_entry.get("duration_ms"),
            "input_snapshot": audit_entry.get("input_snapshot"),
            "output_snapshot": audit_entry.get("output_snapshot"),
        },
    }


def main() -> None:
    queries = sys.argv[1:] or DEFAULT_QUERIES
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Warm import + tool registry once.
    parser = ParserAgent()

    runs = []
    for q in queries:
        print(f"\n== Running: {q!r} ==", flush=True)
        try:
            result = _run_once(parser, q)
            runs.append(result)
            print(
                f"  iterations={result['iterations']} "
                f"terminated_by={result['terminated_by']} "
                f"latency_ms={result['elapsed_ms']} "
                f"tools={result['tools_called']}",
                flush=True,
            )
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
            runs.append({"raw_query": q, "error": f"{type(e).__name__}: {e}"})

    latencies = [r["elapsed_ms"] for r in runs if "elapsed_ms" in r]
    summary = {
        "queries_run": len(runs),
        "ok_count": len(latencies),
        "mean_latency_ms": int(statistics.mean(latencies)) if latencies else None,
        "median_latency_ms": int(statistics.median(latencies)) if latencies else None,
        "max_latency_ms": max(latencies) if latencies else None,
        "min_latency_ms": min(latencies) if latencies else None,
    }
    out_path = OUT_DIR / "parser_react_demo.json"
    out_path.write_text(
        json.dumps({"summary": summary, "runs": runs}, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nSaved: {out_path}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
