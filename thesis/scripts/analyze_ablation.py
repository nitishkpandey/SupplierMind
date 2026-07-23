"""
thesis/scripts/analyze_ablation.py

Deterministic. NO LLM, NO cost. Builds the component-ablation ladder.

The P1 -> P2 -> P3 comparison is already a coarse ablation (parametric ->
+retrieval -> +full agentic). This adds the missing rung inside P3 by removing
the compliance/evidence gate, so we can separate two contributions:

  P2 (RAG, semantic only)
      │  + structured discovery (SQL constraint filtering) and evidence-gated
      │    ranking, but with the compliance GATE removed
  P3 no-compliance
      │  + the compliance / quote-or-fail gate
  P3 full

Reports Precision@5 (overall and by tier) for the three rungs, so the delta at
each step shows what that component is worth.

Run (after run_10k_benchmark.py --p3 --ablation no_compliance):
    python thesis/scripts/analyze_ablation.py
"""

from __future__ import annotations

import glob
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "thesis" / "results" / "10k"
ABL = ROOT / "thesis" / "results" / "10k_ablation_no_compliance"


def load(dir_path):
    return [json.loads(Path(f).read_text()) for f in sorted(glob.glob(str(dir_path / "run_*.json")))]


def p5_overall_and_tier(runs, system):
    """Return (overall_mean, {tier: mean}) of query-level P@5 across runs."""
    by_q = defaultdict(list)
    tier = {}
    for r in runs:
        for row in r["per_query_metrics"].get(system, []):
            by_q[row["query_id"]].append(row.get("precision_at_5", 0.0))
            tier[row["query_id"]] = row.get("difficulty")
    q_means = {q: st.mean(v) for q, v in by_q.items()}
    overall = st.mean(q_means.values()) if q_means else float("nan")
    tiers = {}
    for t in ("simple", "medium", "hard"):
        vals = [q_means[q] for q in q_means if tier.get(q) == t]
        if vals:
            tiers[t] = st.mean(vals)
    return overall, tiers


def main() -> None:
    main_runs = load(MAIN)
    abl_runs = load(ABL)
    if not main_runs:
        raise SystemExit(f"no main runs in {MAIN}")
    if not abl_runs:
        raise SystemExit(f"no ablation runs in {ABL} — run: run_10k_benchmark.py --p3 --ablation no_compliance")

    rungs = [
        ("P2 RAG (semantic only)", *p5_overall_and_tier(main_runs, "p2_rag")),
        ("P3 no-compliance (+structured discovery/ranking)", *p5_overall_and_tier(abl_runs, "suppliermind")),
        ("P3 full (+compliance gate)", *p5_overall_and_tier(main_runs, "suppliermind")),
    ]

    print("=" * 74)
    print(f"Component ablation ladder — Precision@5  (main {len(main_runs)} runs, ablation {len(abl_runs)} runs)")
    print("=" * 74)
    print(f"\n  {'rung':<50}{'overall':>9}{'simple':>8}{'medium':>8}{'hard':>7}")
    prev = None
    for name, overall, tiers in rungs:
        delta = f"  (Δ {overall - prev:+.3f})" if prev is not None else ""
        print(f"  {name:<50}{overall:>9.3f}{tiers.get('simple', float('nan')):>8.3f}"
              f"{tiers.get('medium', float('nan')):>8.3f}{tiers.get('hard', float('nan')):>7.3f}{delta}")
        prev = overall
    print("\nReading each Δ: P2→no-compliance = value of structured discovery + ranking;")
    print("no-compliance→full = value of the compliance / quote-or-fail gate.")


if __name__ == "__main__":
    main()
