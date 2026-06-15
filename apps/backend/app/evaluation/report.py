"""
app/evaluation/report.py — Generates evaluation report from runner results.

Produces two outputs:
1. thesis_report.json — structured data for thesis Chapter 5
2. Console summary — what to put in thesis tables directly

The report answers all three research questions:
  RQ1: Answered by the architecture (Phase 2)
  RQ2: Answered by P@5, CSR, MRR comparison tables (this file)
  RQ3: Answered by the failure analysis section (which queries failed?)
"""

from __future__ import annotations

import json
import logging
import statistics
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RESULTS_FILE = Path(__file__).parent.parent.parent / "data" / "evaluation_results.json"
REPORT_FILE = Path(__file__).parent.parent.parent / "data" / "thesis_report.json"


def generate_thesis_report(results_path: Path = RESULTS_FILE) -> dict:
    """
    Generate a structured report from evaluation results.

    Args:
        results_path: Path to evaluation_results.json from runner

    Returns:
        Report dict (also saved to thesis_report.json)
    """
    if not results_path.exists():
        raise FileNotFoundError(
            f"Evaluation results not found: {results_path}\n"
            "Run first: uv run python scripts/run_evaluation.py"
        )

    with open(results_path, encoding="utf-8") as f:
        results = json.load(f)

    aggregated = results.get("aggregated", {})
    per_query = results.get("per_query_metrics", {})

    report: dict[str, Any] = {
        "metadata": {
            "run_id": results.get("run_id"),
            "timestamp": results.get("timestamp"),
            "query_count": results.get("query_count"),
        },

        # ── RQ2: Performance comparison table ─────────────────────────
        "rq2_performance_comparison": _build_comparison_table(aggregated),

        # ── Difficulty breakdown ───────────────────────────────────────
        "difficulty_breakdown": _build_difficulty_breakdown(aggregated),

        # ── RQ3: Failure analysis ──────────────────────────────────────
        "rq3_failure_analysis": _build_failure_analysis(per_query),

        # ── Statistical significance note ─────────────────────────────
        "statistical_note": (
            "Results are based on 25 queries across 3 difficulty levels. "
            "Standard deviations are provided per metric. "
            "This is a proof-of-concept scale evaluation appropriate for an MSc thesis. "
            "Production evaluation would require a larger benchmark with expert annotation."
        ),

        # ── Thesis table — copy these numbers directly ─────────────────
        "thesis_table": _format_thesis_table(aggregated),
    }

    # Save report
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    _print_thesis_tables(report)
    logger.info("Thesis report saved to: %s", REPORT_FILE)

    return report


def _build_comparison_table(aggregated: dict) -> dict:
    """Build the main comparison table for thesis Chapter 5."""
    systems = ["suppliermind", "manual_simulation", "keyword_sql"]
    table = {}
    for system in systems:
        if system not in aggregated:
            continue
        m = aggregated[system]
        table[system] = {
            "precision_at_5": {
                "mean": round(m["mean_precision_at_5"], 4),
                "std": round(m["std_precision_at_5"], 4),
            },
            "constraint_satisfaction_rate": {
                "mean": round(m["mean_csr"], 4),
                "std": round(m["std_csr"], 4),
            },
            "mean_reciprocal_rank": {
                "mean": round(m["mean_reciprocal_rank"], 4),
                "std": round(m["std_mrr"], 4),
            },
            "execution_time_ms": {
                "mean": round(m["mean_execution_time_ms"], 0),
                "std": round(m["std_execution_time_ms"], 0),
            },
        }
    return table


def _build_difficulty_breakdown(aggregated: dict) -> dict:
    """Break down SupplierMind P@5 by query difficulty."""
    if "suppliermind" not in aggregated:
        return {}
    m = aggregated["suppliermind"]
    return {
        "suppliermind": {
            "simple_p5": round(m["simple_p5"], 4),
            "medium_p5": round(m["medium_p5"], 4),
            "hard_p5": round(m["hard_p5"], 4),
        }
    }


def _build_failure_analysis(per_query: dict) -> dict:
    """
    Identify queries where SupplierMind performed poorly.
    Answers RQ3: "Under what conditions does the system fail?"
    """
    sm_queries = per_query.get("suppliermind", [])
    if not sm_queries:
        return {"message": "No SupplierMind results available for failure analysis"}

    failed_queries = []
    low_csr_queries = []
    slow_queries = []

    for q in sm_queries:
        p5 = q.get("precision_at_5", 0)
        csr = q.get("constraint_satisfaction_rate", 0)
        exec_ms = q.get("execution_time_ms", 0)

        if p5 == 0.0:
            failed_queries.append({
                "query_number": q["query_number"],
                "difficulty": q["difficulty"],
                "precision_at_5": p5,
                "reason": "No relevant suppliers in top-5 results",
            })

        if csr < 0.6:
            low_csr_queries.append({
                "query_number": q["query_number"],
                "difficulty": q["difficulty"],
                "csr": round(csr, 3),
                "reason": "Constraint satisfaction below 60%",
            })

        if exec_ms > 45000:
            slow_queries.append({
                "query_number": q["query_number"],
                "execution_time_ms": exec_ms,
                "reason": "Execution > 45 seconds (likely LLM rate limit)",
            })

    all_p5 = [q.get("precision_at_5", 0) for q in sm_queries]
    p5_by_difficulty = {
        d: [q.get("precision_at_5", 0) for q in sm_queries if q.get("difficulty") == d]
        for d in ["simple", "medium", "hard"]
    }

    return {
        "total_queries_evaluated": len(sm_queries),
        "zero_precision_queries": failed_queries,
        "zero_precision_count": len(failed_queries),
        "low_csr_queries": low_csr_queries,
        "slow_queries": slow_queries,
        "performance_degradation_by_difficulty": {
            d: round(statistics.mean(scores), 4) if scores else 0.0
            for d, scores in p5_by_difficulty.items()
        },
        "observations": _generate_observations(
            failed_queries, low_csr_queries, p5_by_difficulty
        ),
    }


def _generate_observations(
    failed: list,
    low_csr: list,
    p5_by_diff: dict,
) -> list[str]:
    """Generate human-readable observations for the thesis discussion."""
    obs = []

    if failed:
        difficulties = [q["difficulty"] for q in failed]
        hard_failures = sum(1 for d in difficulties if d == "hard")
        obs.append(
            f"{len(failed)} queries returned zero Precision@5. "
            f"{hard_failures} of these were hard queries with 5+ constraints, "
            f"suggesting constraint combination complexity is a primary failure mode."
        )

    if low_csr:
        obs.append(
            f"{len(low_csr)} queries had CSR below 60%, indicating "
            f"the compliance agent struggled with multi-constraint satisfaction "
            f"on complex queries."
        )

    simple = p5_by_diff.get("simple", [])
    hard = p5_by_diff.get("hard", [])
    if simple and hard:
        simple_mean = statistics.mean(simple)
        hard_mean = statistics.mean(hard)
        drop = simple_mean - hard_mean
        if drop > 0.1:
            obs.append(
                f"Performance degrades with query complexity: simple queries achieve "
                f"P@5={simple_mean:.2f} vs hard queries at P@5={hard_mean:.2f} "
                f"(delta={drop:.2f}). This is expected behaviour — more constraints "
                f"create a harder search problem."
            )

    return obs


def _format_thesis_table(aggregated: dict) -> str:
    """
    Format a LaTeX-ready table for the thesis.
    Paste directly into your Chapter 5 LaTeX source.
    """
    lines = [
        "% Copy this into your thesis LaTeX (Chapter 5: Results)",
        "\\begin{table}[h]",
        "\\centering",
        "\\caption{Evaluation Results: SupplierMind vs Baselines on SupplierBench-25}",
        "\\label{tab:results}",
        "\\begin{tabular}{lccc}",
        "\\hline",
        "\\textbf{System} & \\textbf{P@5} & \\textbf{CSR} & \\textbf{MRR} \\\\",
        "\\hline",
    ]

    display_names = {
        "suppliermind": "SupplierMind (ours)",
        "manual_simulation": "Baseline B: Manual Simulation",
        "keyword_sql": "Baseline A: Keyword SQL",
    }
    order = ["suppliermind", "manual_simulation", "keyword_sql"]

    for key in order:
        if key not in aggregated:
            continue
        m = aggregated[key]
        name = display_names.get(key, key)
        p5 = m["mean_precision_at_5"]
        csr = m["mean_csr"]
        mrr = m["mean_reciprocal_rank"]
        lines.append(
            f"{name} & {p5:.3f} & {csr:.3f} & {mrr:.3f} \\\\"
        )

    lines += [
        "\\hline",
        "\\end{tabular}",
        "\\end{table}",
    ]
    return "\n".join(lines)


def _print_thesis_tables(report: dict) -> None:
    """Print all thesis-ready numbers to console."""
    print("\n" + "=" * 80)
    print("THESIS RESULTS — Chapter 5: Evaluation")
    print("=" * 80)

    comp = report.get("rq2_performance_comparison", {})
    labels = {
        "suppliermind": "SupplierMind (ours)",
        "manual_simulation": "Baseline B: Manual Sim",
        "keyword_sql": "Baseline A: Keyword SQL",
    }

    print(f"\n{'System':<30} {'P@5':>8} {'±std':>6} {'CSR':>8} {'±std':>6} {'MRR':>8} {'±std':>6}")
    print("-" * 80)
    for key, label in labels.items():
        if key not in comp:
            continue
        m = comp[key]
        print(
            f"{label:<30} "
            f"{m['precision_at_5']['mean']:>8.3f} "
            f"±{m['precision_at_5']['std']:>5.3f} "
            f"{m['constraint_satisfaction_rate']['mean']:>8.3f} "
            f"±{m['constraint_satisfaction_rate']['std']:>5.3f} "
            f"{m['mean_reciprocal_rank']['mean']:>8.3f} "
            f"±{m['mean_reciprocal_rank']['std']:>5.3f}"
        )

    diff = report.get("difficulty_breakdown", {}).get("suppliermind", {})
    if diff:
        print("\nSupplierMind P@5 by query difficulty:")
        print(f"  Simple  (1-2 constraints):   {diff.get('simple_p5', 0):.3f}")
        print(f"  Medium  (3-4 constraints):   {diff.get('medium_p5', 0):.3f}")
        print(f"  Hard    (5-6 constraints):   {diff.get('hard_p5', 0):.3f}")

    obs = report.get("rq3_failure_analysis", {}).get("observations", [])
    if obs:
        print("\nRQ3 — Failure Analysis Observations:")
        for i, o in enumerate(obs, 1):
            print(f"  {i}. {o}")

    print("\n--- LaTeX Table (paste into thesis) ---")
    print(report.get("thesis_table", ""))
    print("=" * 80)
