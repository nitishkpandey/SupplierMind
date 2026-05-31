"""
backend/scripts/build_scale_comparison.py
Build the 100-vs-10K side-by-side comparison artifacts for Chapter 5.

Inputs (defaults can be overridden):
  --baseline-report   100-supplier thesis_report.json
  --scale-report      10K-supplier thesis_report.json

Outputs:
  scale_comparison_table.md   (Markdown side-by-side)
  results_table_10k.tex       (LaTeX, two-column variant)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_BASELINE = (
    Path(__file__).parent.parent.parent
    / "Documents"
    / "thesis_evidence"
    / "week_2_production"
    / "baseline_100_thesis_report.json"
)
DEFAULT_SCALE = (
    Path(__file__).parent.parent.parent
    / "Documents"
    / "thesis_evidence"
    / "week_2_production"
    / "supplierbench_10k"
    / "thesis_report.json"
)
DEFAULT_OUT_DIR = (
    Path(__file__).parent.parent.parent
    / "Documents"
    / "thesis_evidence"
    / "week_2_production"
)

SYSTEMS = [
    ("suppliermind", "SupplierMind (ours)"),
    ("manual_simulation", "Baseline B: Manual Sim"),
    ("keyword_sql", "Baseline A: Keyword SQL"),
]


def _get(d: dict, *keys, default=0.0):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def build_markdown(baseline: dict, scale: dict) -> str:
    rows = []
    head = (
        "| System | P@5 (100) | CSR (100) | MRR (100) | P@5 (10K) | "
        "CSR (10K) | MRR (10K) | ΔP@5 |"
    )
    sep = "|" + "|".join(["---"] * 8) + "|"
    rows.append(head)
    rows.append(sep)
    for key, label in SYSTEMS:
        b = _get(baseline, "rq2_performance_comparison", key)
        s = _get(scale, "rq2_performance_comparison", key)
        if not b or not s:
            continue
        bp = _get(b, "precision_at_5", "mean")
        bc = _get(b, "constraint_satisfaction_rate", "mean")
        bm = _get(b, "mean_reciprocal_rank", "mean")
        sp = _get(s, "precision_at_5", "mean")
        sc = _get(s, "constraint_satisfaction_rate", "mean")
        sm = _get(s, "mean_reciprocal_rank", "mean")
        delta = sp - bp
        rows.append(
            f"| {label} | {bp:.3f} | {bc:.3f} | {bm:.3f} | "
            f"{sp:.3f} | {sc:.3f} | {sm:.3f} | {delta:+.3f} |"
        )

    diff_b = _get(baseline, "difficulty_breakdown", "suppliermind", default={})
    diff_s = _get(scale, "difficulty_breakdown", "suppliermind", default={})
    body = "\n".join(rows)
    diff_block = (
        "\n\n### SupplierMind P@5 by difficulty\n\n"
        "| Difficulty | 100 suppliers | 10K suppliers | Δ |\n"
        "|---|---|---|---|\n"
        f"| Simple | {diff_b.get('simple_p5', 0):.3f} | {diff_s.get('simple_p5', 0):.3f} | "
        f"{diff_s.get('simple_p5', 0) - diff_b.get('simple_p5', 0):+.3f} |\n"
        f"| Medium | {diff_b.get('medium_p5', 0):.3f} | {diff_s.get('medium_p5', 0):.3f} | "
        f"{diff_s.get('medium_p5', 0) - diff_b.get('medium_p5', 0):+.3f} |\n"
        f"| Hard | {diff_b.get('hard_p5', 0):.3f} | {diff_s.get('hard_p5', 0):.3f} | "
        f"{diff_s.get('hard_p5', 0) - diff_b.get('hard_p5', 0):+.3f} |\n"
    )
    return (
        "# SupplierBench-25 — Scale Comparison (100 vs 10,000 suppliers)\n\n"
        + body
        + diff_block
    )


def build_latex(baseline: dict, scale: dict) -> str:
    lines = [
        "% scale_comparison_table.tex — Chapter 5 evidence",
        "\\begin{table}[h]",
        "\\centering",
        "\\caption{SupplierBench-25 results at 100 vs 10{,}000 supplier scale}",
        "\\label{tab:scale}",
        "\\begin{tabular}{lcccccc}",
        "\\hline",
        " & \\multicolumn{3}{c}{100 suppliers} & \\multicolumn{3}{c}{10{,}000 suppliers} \\\\",
        "\\textbf{System} & P@5 & CSR & MRR & P@5 & CSR & MRR \\\\",
        "\\hline",
    ]
    for key, label in SYSTEMS:
        b = _get(baseline, "rq2_performance_comparison", key)
        s = _get(scale, "rq2_performance_comparison", key)
        if not b or not s:
            continue
        bp = _get(b, "precision_at_5", "mean")
        bc = _get(b, "constraint_satisfaction_rate", "mean")
        bm = _get(b, "mean_reciprocal_rank", "mean")
        sp = _get(s, "precision_at_5", "mean")
        sc = _get(s, "constraint_satisfaction_rate", "mean")
        sm = _get(s, "mean_reciprocal_rank", "mean")
        lines.append(
            f"{label} & {bp:.3f} & {bc:.3f} & {bm:.3f} & "
            f"{sp:.3f} & {sc:.3f} & {sm:.3f} \\\\"
        )
    lines += ["\\hline", "\\end{tabular}", "\\end{table}"]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline-report", type=Path, default=DEFAULT_BASELINE)
    p.add_argument("--scale-report", type=Path, default=DEFAULT_SCALE)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = p.parse_args()

    with open(args.baseline_report, encoding="utf-8") as f:
        baseline = json.load(f)
    with open(args.scale_report, encoding="utf-8") as f:
        scale = json.load(f)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    md = build_markdown(baseline, scale)
    md_path = args.out_dir / "scale_comparison_table.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    tex = build_latex(baseline, scale)
    tex_path = args.out_dir / "supplierbench_10k" / "results_table_10k.tex"
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex)

    print(f"Wrote: {md_path}")
    print(f"Wrote: {tex_path}")
    print()
    print(md)


if __name__ == "__main__":
    main()
