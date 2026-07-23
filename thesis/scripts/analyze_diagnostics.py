"""
thesis/scripts/analyze_diagnostics.py

Deterministic. NO LLM, NO cost. Reads the INSTRUMENTED 10k runs and computes the
diagnostic experiments that need the extra fields the runner now captures
(parser output, tool calls, token usage, provider-pacing time):

  intent_resolution   how accurately P3's parser extracts each constraint type
  error_taxonomy      categorised counts of P3 failures
  tool_access         which parser tools fire, and success with/without them
  prompt_efficiency    LLM calls + tokens per query, per system
  clean_latency        wall time minus provider-pacing = real compute time
  task_success_rate    fraction of queries with >=1 correct supplier in top-5

Run (after an instrumented run of run_10k_benchmark.py):
    python thesis/scripts/analyze_diagnostics.py
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "backend"
UNIT_WORDS = ("month", "day", "tonne", "kg", "units", "meter", "litre", "liter", "/")


def _has(v):
    return v is not None and v != [] and v != ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "thesis" / "results" / "10k"))
    ap.add_argument("--benchmark", default=str(ROOT / "thesis" / "benchmark" / "supplierbench25_10k.json"))
    args = ap.parse_args()

    files = sorted(glob.glob(str(Path(args.dir) / "run_*.json")))
    runs = [json.loads(Path(f).read_text()) for f in files]
    bench = {q["id"]: q for q in json.loads(Path(args.benchmark).read_text())}
    # only proceed on instrumented runs
    if not any("parsed_constraints" in (r["per_query_metrics"]["suppliermind"][0])
               for r in runs if r["per_query_metrics"].get("suppliermind")):
        raise SystemExit("These runs are not instrumented (no parsed_constraints). Re-run the benchmark with the updated runner.")

    print("=" * 72)
    print(f"DIAGNOSTICS — {len(runs)} instrumented run(s) in {Path(args.dir).name}")
    print("=" * 72)

    # ── prompt efficiency + clean latency + task success (per system) ─────
    print("\n[Prompt efficiency & latency] per-query means")
    print(f"  {'system':<18}{'llm_calls':>10}{'prompt_tok':>12}{'compl_tok':>11}"
          f"{'wall_ms':>10}{'pacing_ms':>11}{'compute_ms':>12}")
    for sysname in ("suppliermind", "p2_rag", "p1_singleprompt"):
        rows = [row for r in runs for row in r["per_query_metrics"].get(sysname, [])]
        if not rows:
            continue
        def m(key):
            vals = [row[key] for row in rows if row.get(key) is not None]
            return st.mean(vals) if vals else float("nan")
        wall = m("execution_time_ms")
        pace = m("pacing_ms")
        compute = st.mean([row["execution_time_ms"] - (row.get("pacing_ms") or 0)
                           for row in rows if row.get("execution_time_ms") is not None])
        print(f"  {sysname:<18}{m('llm_calls'):>10.1f}{m('prompt_tokens'):>12.0f}"
              f"{m('completion_tokens'):>11.0f}{wall:>10.0f}{pace:>11.0f}{compute:>12.0f}")

    print("\n[Task success rate] fraction of queries with >=1 correct supplier in top-5")
    for sysname in ("suppliermind", "p2_rag", "p1_singleprompt"):
        rows = [row for r in runs for row in r["per_query_metrics"].get(sysname, [])]
        if not rows:
            continue
        succ = st.mean([1.0 if (row.get("precision_at_5") or 0) > 0 else 0.0 for row in rows])
        print(f"  {sysname:<18}{succ:>6.3f}")

    # ── intent resolution (P3 parser vs ground-truth constraints) ─────────
    sm = [row for r in runs for row in r["per_query_metrics"].get("suppliermind", [])]
    fields = ["category", "country", "certifications", "capacity", "lead_time"]
    correct = defaultdict(int)
    total = defaultdict(int)
    for row in sm:
        p = row.get("parsed_constraints") or {}
        c = bench.get(row["query_id"], {}).get("constraints", {})
        # category
        total["category"] += 1
        correct["category"] += int((p.get("category_hint") or p.get("industry_context")) == c.get("category"))
        # country (only when the query specifies one)
        if c.get("country"):
            total["country"] += 1
            correct["country"] += int(p.get("location_country") == c["country"])
        # certifications (set match)
        total["certifications"] += 1
        correct["certifications"] += int(set(p.get("certifications") or []) == set(c.get("certs") or []))
        # capacity: extracted iff expected, and value matches
        total["capacity"] += 1
        exp_cap = _has(c.get("min_cap"))
        got_cap = _has(p.get("capacity_min"))
        cap_ok = (exp_cap == got_cap) and (not exp_cap or p.get("capacity_min") == c.get("min_cap"))
        correct["capacity"] += int(cap_ok)
        # lead time
        total["lead_time"] += 1
        exp_lt = _has(c.get("max_lead"))
        got_lt = _has(p.get("lead_time_max_days"))
        lt_ok = (exp_lt == got_lt) and (not exp_lt or p.get("lead_time_max_days") == c.get("max_lead"))
        correct["lead_time"] += int(lt_ok)

    print("\n[Intent resolution] P3 parser extraction accuracy vs ground truth")
    tot_c = tot_n = 0
    for f in fields:
        if total[f]:
            tot_c += correct[f]; tot_n += total[f]
            print(f"  {f:<16}{correct[f]/total[f]:>6.3f}  ({correct[f]}/{total[f]})")
    print(f"  {'OVERALL':<16}{tot_c/tot_n:>6.3f}  ({tot_c}/{tot_n})")

    # ── error taxonomy (P3) ───────────────────────────────────────────────
    tax = Counter()
    for row in sm:
        p = row.get("parsed_constraints") or {}
        c = bench.get(row["query_id"], {}).get("constraints", {})
        term = row.get("react_terminated_by")
        prod = str(p.get("product_type") or "")
        polluted = any(u in prod.lower() for u in UNIT_WORDS) or any(ch.isdigit() for ch in prod)
        missed = (
            (set(p.get("certifications") or []) != set(c.get("certs") or []))
            or (_has(c.get("min_cap")) and not _has(p.get("capacity_min")))
            or (_has(c.get("max_lead")) and not _has(p.get("lead_time_max_days")))
        )
        if term in ("parse_failed", "max_iterations"):
            tax["parse_failure_or_maxiter"] += 1
        if polluted:
            tax["polluted_product_string"] += 1
        if missed:
            tax["missed_a_constraint"] += 1
        if (row.get("precision_at_5") or 0) == 0 and not missed and not polluted:
            tax["clean_parse_but_zero_precision"] += 1
    print(f"\n[Error taxonomy] P3, pooled over {len(sm)} query-runs (categories overlap)")
    for k, v in tax.most_common():
        print(f"  {k:<32}{v:>4}  ({v/len(sm):.1%})")

    # ── tool access ───────────────────────────────────────────────────────
    tool_freq = Counter()
    per_tool_p5 = defaultdict(list)
    tools_per_q = []
    for row in sm:
        tools = row.get("tools_used") or []
        tools_per_q.append(len(tools))
        for t in set(tools):
            tool_freq[t] += 1
            per_tool_p5[t].append(row.get("precision_at_5") or 0)
    print(f"\n[Tool access] P3 parser, avg {st.mean(tools_per_q):.1f} tool-calls/query")
    print(f"  {'tool':<26}{'used_in_queries':>16}{'mean_P@5_when_used':>20}")
    for t, n in tool_freq.most_common():
        print(f"  {t:<26}{n:>16}{st.mean(per_tool_p5[t]):>20.3f}")


if __name__ == "__main__":
    main()
