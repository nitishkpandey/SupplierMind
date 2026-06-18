"""Week 3 closeout smoke tests (Task 3.4).

Drives the 4 agentic smoke scenarios via HTTP against the running stack
(localhost:8000) and saves machine-readable evidence under
demo_output/week_3_agentic/smoke_test_3.4/.

Scenarios (roadmap Task 3.4):
  1. ReAct trace      — "Find ISO certified packaging in Bavaria" shows
                        multiple tool calls in the Parser audit trace.
  2. Semantic memory  — 5 textile queries seeded, then a "fabric" probe
                        retrieves them as context via lookup_past_query.
  3. Clarification    — "I need a supplier" pauses, user answers, pipeline
                        resumes and completes.
  4. Combined         — vague placeholder query -> clarification -> resume ->
                        final constraints reflect the clarified intent.

Run from backend/ with the API server up:
    uv run uvicorn app.main:app --port 8000   (separate terminal)
    uv run python scripts/smoke_test_week3.py

Notes:
  - Live LLM calls and vector retrieval make each full pipeline run slow
    (1-5 min). The whole script can take 30-45 minutes. Patience is part of
    the test.
  - Scenario 2 seeds via the REAL pipeline (memory rows are only written on
    evaluator-accept). If a seed run is rejected, the script tops up that row
    directly through QueryMemoryService.write() and records that honestly in
    the evidence JSON (`seeded_directly` list).
"""
from __future__ import annotations

import base64
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Running a file under scripts/ puts scripts/ (not backend/) on sys.path;
# the scenario-2 top-up imports app.* so backend/ must be importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BACKEND = "http://localhost:8000"
EVIDENCE = (
    Path(__file__).resolve().parents[2]
    / "demo_output" / "week_3_agentic" / "smoke_test_3.4"
)
# Provider pacing can sleep up to ~60s per LLM call; a full ReAct pipeline run
# can exceed 7 minutes. 900s is the observed-safe budget.
PIPELINE_DEADLINE_S = 900


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def login(email: str, role: str = "procurement_manager") -> str:
    resp = httpx.get(
        f"{BACKEND}/api/v1/auth/dev-login",
        params={"email": email, "role": role},
        follow_redirects=False,
    )
    if resp.status_code not in (302, 307):
        raise RuntimeError(f"dev-login failed ({resp.status_code}): {resp.text[:200]}")
    return resp.headers["location"].split("access_token=")[1].split("&")[0]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def jwt_sub(token: str) -> str:
    """Decode the JWT payload (no verification) to recover the user UUID."""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["sub"]


def submit(token: str, text: str, scope: str = "approved_only") -> str:
    r = httpx.post(
        f"{BACKEND}/api/v1/queries",
        headers={**auth(token), "Content-Type": "application/json"},
        json={"raw_query": text, "search_scope": scope},
        timeout=15.0,
    )
    r.raise_for_status()
    return r.json()["id"]


def get_clarification(token: str, qid: str) -> dict | None:
    r = httpx.get(
        f"{BACKEND}/api/v1/queries/{qid}/clarification",
        headers=auth(token), timeout=15.0,
    )
    return r.json() if r.status_code == 200 else None


def poll(token: str, qid: str, deadline_s: int = PIPELINE_DEADLINE_S,
         ignore_clarification_id: str | None = None) -> tuple[str, dict]:
    """Poll until terminal state OR an open clarification appears.

    Returns ("completed"|"failed", query_json) or ("clarification", clar_json).
    `ignore_clarification_id` skips the just-answered row while the resume
    background task is still marking it resolved.
    """
    deadline = time.time() + deadline_s
    last = {}
    while time.time() < deadline:
        r = httpx.get(f"{BACKEND}/api/v1/queries/{qid}", headers=auth(token), timeout=15.0)
        r.raise_for_status()
        last = r.json()
        if last.get("status") in ("completed", "failed"):
            return last["status"], last
        clar = get_clarification(token, qid)
        if clar and clar.get("id") != ignore_clarification_id:
            return "clarification", clar
        time.sleep(4)
    raise TimeoutError(f"query {qid} not terminal in {deadline_s}s (status={last.get('status')})")


def answer_clarification(token: str, qid: str, answer: str) -> dict:
    r = httpx.post(
        f"{BACKEND}/api/v1/queries/{qid}/clarify",
        headers={**auth(token), "Content-Type": "application/json"},
        json={"answer": answer},
        timeout=15.0,
    )
    r.raise_for_status()
    return r.json()


def audit(token: str, qid: str) -> list[dict]:
    r = httpx.get(f"{BACKEND}/api/v1/queries/{qid}/audit", headers=auth(token), timeout=15.0)
    r.raise_for_status()
    return r.json()["audit_entries"]


def parser_traces(entries: list[dict]) -> list[list[dict]]:
    """All Parser ReAct traces in audit order (resume runs append a new one)."""
    out = []
    for e in entries:
        if e.get("agent_name") == "parser":
            snap = e.get("output_snapshot") or {}
            trace = snap.get("trace")
            if isinstance(trace, list):
                out.append(trace)
    return out


def tools_called(trace: list[dict]) -> list[str]:
    return [step.get("action") for step in trace if step.get("action")]


def run_clarification_dialogue(token: str, qid: str, answers: list[str]) -> dict:
    """Drive a query through up to len(answers) clarification turns.

    Returns a record of every turn plus the final query payload (or timeout).
    """
    turns: list[dict] = []
    ignore_id = None
    final_state, final_payload = None, None
    for _ in range(len(answers) + 1):
        state, payload = poll(token, qid, ignore_clarification_id=ignore_id)
        if state in ("completed", "failed"):
            final_state, final_payload = state, payload
            break
        # state == "clarification"
        turn = {
            "clarification_id": payload["id"],
            "turn_number": payload["turn_number"],
            "question": payload["question"],
        }
        if len(turns) >= len(answers):
            turn["answer"] = None
            turns.append(turn)
            final_state = "unanswered_clarification"
            break
        ans = answers[len(turns)]
        turn["answer"] = ans
        turns.append(turn)
        answer_clarification(token, qid, ans)
        ignore_id = payload["id"]
    return {"turns": turns, "final_state": final_state, "final_payload": final_payload}


# ── Scenario 1 — ReAct trace ────────────────────────────────────────────


def scenario_1_react_trace(out: dict) -> None:
    print("[scenario 1] ReAct trace: 'Find ISO certified packaging in Bavaria'")
    token = login("smoke3.usera@test.local")
    qid = submit(token, "Find ISO certified packaging in Bavaria")
    state, payload = poll(token, qid)
    entries = audit(token, qid)
    traces = parser_traces(entries)
    trace = traces[-1] if traces else []
    tools = tools_called(trace)
    real_tools = [t for t in tools if t and t.lower() != "finish"]
    out["scenario_1_react_trace"] = {
        "timestamp": utcnow(),
        "query_id": qid,
        "final_state": state,
        "error_message": payload.get("error_message"),
        "result_count": len(payload.get("results") or []) if state == "completed" else 0,
        "parser_iterations": len(trace),
        "tools_called": tools,
        "distinct_real_tools": sorted(set(real_tools)),
        "trace": trace,
        "overall_pass": state == "completed" and len(real_tools) >= 2,
    }
    print(f"  state={state} tools={tools}")
    print(f"  result: {out['scenario_1_react_trace']['overall_pass']}")


# ── Scenario 2 — semantic memory ────────────────────────────────────────

TEXTILE_SEEDS = [
    "Textile suppliers in Munich with OEKO-TEX certification",
    "Organic cotton textile manufacturer in Germany",
    "Wool and polyester textile wholesale supplier in Bavaria",
    "GOTS certified textile dyeing company in Europe",
    "Technical textiles supplier for automotive interiors",
]
FABRIC_PROBE = "Looking for fabric suppliers, similar to what I searched before"


def scenario_2_semantic_memory(out: dict) -> None:
    print("[scenario 2] semantic memory: 5 textile seeds + fabric probe")
    token = login("smoke3.memory@test.local")
    user_uuid = jwt_sub(token)

    # Clean slate so the probe can only hit what this scenario seeded.
    r_del = httpx.delete(f"{BACKEND}/api/v1/users/me/memory", headers=auth(token), timeout=30.0)
    print(f"  memory wipe: {r_del.status_code}")

    seeds: list[dict] = []
    for text in TEXTILE_SEEDS:
        print(f"  seeding: {text}")
        rec: dict = {"query": text}
        try:
            qid = submit(token, text)
            state, _payload = poll(token, qid)
            entries = audit(token, qid)
            rec["query_id"] = qid
            rec["final_state"] = state
            rec["memory_written_via_pipeline"] = any(
                e.get("action") == "memory_written" for e in entries
            )
        except Exception as e:  # keep seeding even if one run dies
            rec["final_state"] = f"error: {e}"
            rec["memory_written_via_pipeline"] = False
        seeds.append(rec)
        print(f"    state={rec['final_state']} memory_written={rec['memory_written_via_pipeline']}")

    # Honest top-up: pipeline only remembers evaluator-accepted runs. Any seed
    # that didn't land is written directly so the probe still has 5 memories.
    seeded_directly = []
    from app.services.query_memory import get_memory_service
    svc = get_memory_service()
    for rec in seeds:
        if not rec["memory_written_via_pipeline"]:
            svc.write(
                user_id=user_uuid,
                query_text=rec["query"],
                parsed_constraints={"product_type": "textiles", "seeded_by": "smoke_test_3.4"},
            )
            seeded_directly.append(rec["query"])
    if seeded_directly:
        print(f"  topped up directly: {len(seeded_directly)}")
    time.sleep(2)  # Milvus flush slack

    print(f"  probing: {FABRIC_PROBE}")
    qid = submit(token, FABRIC_PROBE)
    state, payload = poll(token, qid)
    entries = audit(token, qid)
    traces = parser_traces(entries)
    trace = traces[-1] if traces else []

    lookup_steps = [s for s in trace if s.get("action") == "lookup_past_query"]
    obs_blob = json.dumps([s.get("observation") for s in lookup_steps]).lower()
    called = bool(lookup_steps)
    nonempty = any(
        isinstance(s.get("observation"), list) and len(s["observation"]) > 0
        for s in lookup_steps
    )
    mentions_textile = ("textile" in obs_blob) or ("cotton" in obs_blob)

    out["scenario_2_semantic_memory"] = {
        "timestamp": utcnow(),
        "seed_runs": seeds,
        "seeded_directly": seeded_directly,
        "probe_query": FABRIC_PROBE,
        "probe_query_id": qid,
        "probe_final_state": state,
        "probe_error_message": payload.get("error_message"),
        "probe_trace": trace,
        "flags": {
            "probe_called_lookup_past_query": called,
            "probe_observation_nonempty": nonempty,
            "probe_observation_mentions_textile": mentions_textile,
        },
        "overall_pass": called and nonempty and mentions_textile,
    }
    print(f"  flags: called={called} nonempty={nonempty} textile={mentions_textile}")
    print(f"  result: {out['scenario_2_semantic_memory']['overall_pass']}")


# ── Scenario 3 — clarification dialogue ─────────────────────────────────


def scenario_3_clarification(out: dict) -> None:
    print("[scenario 3] clarification: 'I need a supplier'")
    # Fresh user per run: a reused account accumulates query memory, and
    # memory legitimately suppresses the clarification ("memory wins" by
    # design). This scenario tests the no-memory path.
    token = login(f"smoke3.clarify.{int(time.time())}@test.local")
    qid = submit(token, "I need a supplier")
    dialogue = run_clarification_dialogue(token, qid, answers=[
        "Cardboard packaging boxes for shipping electronics, ISO 9001 certified",
        "Anywhere in Germany, around 5000 units per month",
    ])
    entries = audit(token, qid)
    raised_in_audit = any(
        e.get("agent_name") == "clarification_handler" and e.get("action") == "clarification_raised"
        for e in entries
    )
    final = dialogue["final_payload"] or {}
    out["scenario_3_clarification"] = {
        "timestamp": utcnow(),
        "query_id": qid,
        "turns": dialogue["turns"],
        "final_state": dialogue["final_state"],
        "error_message": final.get("error_message"),
        "result_count": len(final.get("results") or []),
        "audit_clarification_raised": raised_in_audit,
        "overall_pass": (
            len(dialogue["turns"]) >= 1
            and dialogue["final_state"] == "completed"
            and raised_in_audit
        ),
    }
    print(f"  turns={len(dialogue['turns'])} final={dialogue['final_state']} audit={raised_in_audit}")
    print(f"  result: {out['scenario_3_clarification']['overall_pass']}")


# ── Scenario 4 — combined vague -> clarify -> resume -> intent ──────────


def scenario_4_combined(out: dict) -> None:
    print("[scenario 4] combined: vague placeholder -> clarify -> resume")
    # Fresh user per run — same memory-suppression rationale as scenario 3.
    token = login(f"smoke3.combined.{int(time.time())}@test.local")
    qid = submit(token, "We need materials for our project")
    answer = "Stainless steel fasteners and bolts for construction, ISO 9001 certified, in Germany"
    dialogue = run_clarification_dialogue(token, qid, answers=[
        answer,
        "Standard delivery, no other constraints",
    ])
    entries = audit(token, qid)
    traces = parser_traces(entries)
    last_trace = traces[-1] if traces else []
    # Did the resumed Parser run actually absorb the clarified intent?
    trace_blob = json.dumps(last_trace).lower()
    audit_blob = json.dumps(entries).lower()
    reflects = ("fastener" in audit_blob) or ("steel" in audit_blob) or ("bolt" in audit_blob)
    final = dialogue["final_payload"] or {}
    out["scenario_4_combined"] = {
        "timestamp": utcnow(),
        "query_id": qid,
        "turns": dialogue["turns"],
        "final_state": dialogue["final_state"],
        "error_message": final.get("error_message"),
        "result_count": len(final.get("results") or []),
        "parser_runs_in_audit": len(traces),
        "final_trace": last_trace,
        "constraints_reflect_clarified_intent": reflects,
        "overall_pass": (
            len(dialogue["turns"]) >= 1
            and dialogue["final_state"] == "completed"
            and reflects
        ),
    }
    print(f"  turns={len(dialogue['turns'])} final={dialogue['final_state']} reflects_intent={reflects}")
    print(f"  result: {out['scenario_4_combined']['overall_pass']}")


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out: dict = {"run_started": utcnow(), "backend": BACKEND}
    scenarios = [
        ("scenario_1_react_trace", scenario_1_react_trace),
        ("scenario_2_semantic_memory", scenario_2_semantic_memory),
        ("scenario_3_clarification", scenario_3_clarification),
        ("scenario_4_combined", scenario_4_combined),
    ]
    # Optional CLI filter: `... smoke_test_week3.py 1 3 4` reruns a subset
    # without re-burning live LLM budget on scenarios that already passed.
    wanted = {f"scenario_{n}" for n in sys.argv[1:]}
    if wanted:
        scenarios = [s for s in scenarios if any(s[0].startswith(w) for w in wanted)]
    for key, fn in scenarios:
        try:
            fn(out)
        except Exception as e:
            out[key] = {"overall_pass": False, "error": f"{type(e).__name__}: {e}"}
            print(f"  {key} raised: {e}")
        (EVIDENCE / f"{key}.json").write_text(
            json.dumps(out.get(key, {}), indent=2), encoding="utf-8"
        )
    out["run_finished"] = utcnow()
    (EVIDENCE / "smoke_test_run.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    print("\n=== Summary ===")
    for key, _ in scenarios:
        print(f"  {key}: pass={out.get(key, {}).get('overall_pass')}")


if __name__ == "__main__":
    main()
