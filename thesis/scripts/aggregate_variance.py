"""
thesis/scripts/aggregate_variance.py

Deterministic. NO LLM, NO cost. Runs on a folder of results JSON files.

The paradigms are nondeterministic (the parser runs at temperature 0.2), so a
single run is not enough. Run the benchmark k times (run_10k_benchmark.py
--runs 5), then this script reports, per system, the mean +/- standard
deviation ACROSS runs for each headline metric — i.e. how stable each number is.
It also lists the queries whose P@5 wobbles most between runs.

Run (after you have >=2 runs in thesis/results/10k/):
    python thesis/scripts/aggregate_variance.py
    python thesis/scripts/aggregate_variance.py --dir thesis/results/10k --glob 'run_*.json'
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYSTEMS = ["suppliermind", "p2_rag", "p1_singleprompt", "keyword_sql", "manual_simulation"]


def per_run_metrics(rows: list[dict]) -> dict | None:
    """Headline metrics for one system in one run, computed from per-query rows."""
    if not rows:
        return None
    costs = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
    return {
        "P@5": statistics.mean(r.get("precision_at_5", 0) for r in rows),
        "MRR": statistics.mean(r.get("reciprocal_rank", 0) for r in rows),
        "CSR": statistics.mean(r.get("constraint_satisfaction_rate", 0) for r in rows),
        "answer_rate": statistics.mean(1.0 if r.get("retrieved_ids") else 0.0 for r in rows),
        "latency_ms": statistics.mean(r.get("execution_time_ms", 0) for r in rows),
        "cost_usd": statistics.mean(costs) if costs else float("nan"),
    }


def mean_sd(values: list[float]) -> tuple[float, float]:
    vals = [v for v in values if v == v]  # drop nan
    if not vals:
        return float("nan"), float("nan")
    return statistics.mean(vals), (statistics.stdev(vals) if len(vals) > 1 else 0.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "thesis" / "results" / "10k"))
    ap.add_argument("--glob", default="run_*.json")
    ap.add_argument("--stability-system", default="suppliermind")
    args = ap.parse_args()

    files = sorted(glob.glob(str(Path(args.dir) / args.glob)))
    if not files:
        raise SystemExit(f"No result files matched {args.dir}/{args.glob}. Run the benchmark first.")

    runs = [json.loads(Path(f).read_text()) for f in files]
    print("=" * 70)
    print(f"Variance across {len(runs)} run(s) in {args.dir}")
    for f in files:
        print(f"  - {Path(f).name}")
    if len(runs) < 2:
        print("  (only one run — SD is 0 by definition; run more for real variance)")
    print("=" * 70)

    # per-system mean +/- SD across runs
    metric_names = ["P@5", "MRR", "CSR", "answer_rate", "latency_ms", "cost_usd"]
    for system in SYSTEMS:
        per_run = [per_run_metrics(r["per_query_metrics"].get(system, [])) for r in runs]
        per_run = [m for m in per_run if m]
        if not per_run:
            continue
        print(f"\n{system}  (n_runs={len(per_run)})")
        print(f"  {'metric':<12}{'mean':>12}{'sd':>12}")
        for name in metric_names:
            mean, sd = mean_sd([m[name] for m in per_run])
            fmt = ".5f" if name == "cost_usd" else (".0f" if name == "latency_ms" else ".3f")
            print(f"  {name:<12}{mean:>12{fmt}}{sd:>12{fmt}}")

    # per-query P@5 stability for one system
    sysname = args.stability_system
    if len(runs) >= 2:
        by_q: dict[str, list[float]] = defaultdict(list)
        difficulty: dict[str, str] = {}
        for r in runs:
            for row in r["per_query_metrics"].get(sysname, []):
                by_q[row["query_id"]].append(row.get("precision_at_5", 0))
                difficulty[row["query_id"]] = row.get("difficulty", "?")
        unstable = sorted(
            ((qid, mean_sd(v)[1], mean_sd(v)[0]) for qid, v in by_q.items() if len(v) > 1),
            key=lambda x: x[1], reverse=True,
        )
        wobbly = [u for u in unstable if u[1] > 0]
        print(f"\nLeast stable P@5 queries for {sysname} (SD across runs), top 5:")
        if not wobbly:
            print("  none — P@5 was identical across all runs")
        for qid, sd, mean in wobbly[:5]:
            print(f"  {qid[:8]}  [{difficulty[qid]:6}]  mean={mean:.3f}  sd={sd:.3f}")


if __name__ == "__main__":
    main()
