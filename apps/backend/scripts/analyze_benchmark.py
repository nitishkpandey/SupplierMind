"""Post-process the three-paradigm benchmark: CIs, plots, extra metrics, archive.

Reads backend/data/evaluation_results.json (written by run_evaluation.py
--paradigms) and produces, under results/run_YYYYMMDD/:

  - evaluation_results.json + thesis_report.json (raw copies)
  - bootstrap_cis.json          95% CIs (1,000 resamples) on P@5, MRR, CSR
  - extra_metrics.json          evidence-link ratio + auditability rubric
  - summary_table.md            per (paradigm, tier) headline table
  - plots/headline_bars.png     mean P@5 / MRR / CSR per paradigm
  - plots/tier_breakdown.png    P@5 per tier per paradigm
  - plots/latency_boxplot.png   per-query latency distribution per paradigm
  - plots/cost_per_query.png    mean cost per query per paradigm

Run from backend/:
    uv run python scripts/analyze_benchmark.py
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
RESULTS_SRC = BACKEND / "data" / "evaluation_results.json"
REPORT_SRC = BACKEND / "data" / "thesis_report.json"
RUN_DIR = BACKEND.parent / "results" / f"run_{datetime.now():%Y%m%d}"
PLOTS = RUN_DIR / "plots"

SYSTEMS = {
    "p1_singleprompt": "P1 single-prompt",
    "p2_rag": "P2 RAG",
    "suppliermind": "P3 SupplierMind",
}
TIERS = ["simple", "medium", "hard"]
N_RESAMPLES = 1000
SEED = 42

# Auditability rubric (0-3), assessed per paradigm by construction:
#   0 = no evidence of any kind (parametric answer only)
#   1 = retrieved source documents identifiable, no per-constraint evidence
#   2 = per-constraint verdicts without quoted evidence
#   3 = per-constraint verdicts with quoted evidence + full reasoning trail
AUDITABILITY_RUBRIC = {
    "p1_singleprompt": {
        "score": 0,
        "rationale": "Names generated from parametric memory; no corpus link, "
                     "no evidence, reasoning is unverifiable model text.",
    },
    "p2_rag": {
        "score": 1,
        "rationale": "Picks are grounded in retrieved corpus documents (IDs "
                     "traceable), but there is no per-constraint verdict and "
                     "no quoted evidence.",
    },
    "suppliermind": {
        "score": 3,
        "rationale": "Per-constraint compliance verdicts with quoted evidence "
                     "(quote-or-fail), ReAct trace and audit log per query.",
    },
}


def bootstrap_ci(values: list[float], n: int = N_RESAMPLES) -> dict:
    rng = random.Random(SEED)
    if not values:
        return {"mean": None, "lo": None, "hi": None}
    means = sorted(
        statistics.fmean(rng.choices(values, k=len(values))) for _ in range(n)
    )
    return {
        "mean": statistics.fmean(values),
        "lo": means[int(0.025 * n)],
        "hi": means[int(0.975 * n)] if n > 1 else means[-1],
        "n_queries": len(values),
        "n_resamples": n,
    }


def evidence_link_ratio(per_query: list[dict], system: str) -> float | None:
    """Fraction of returned suppliers backed by checkable evidence.

    P3: supplier counted when compliance_data carries at least one verdict
    with a non-empty evidence/quote field for it. P2: returned IDs exist in
    the corpus by construction (retrieval), but carry no per-constraint
    evidence, so the ratio measures corpus-linkage: matched IDs / returned.
    P1: same corpus-linkage definition; matched names / suggested names.
    """
    linked = 0
    total = 0
    for q in per_query:
        ids = q.get("retrieved_ids") or []
        if system == "suppliermind":
            evid = set()
            for c in q.get("compliance_data") or []:
                sid = str(c.get("supplier_id", ""))
                verdicts = c.get("compliance_results") or []
                if isinstance(verdicts, list) and any(
                    (v.get("evidence") or v.get("quote") or v.get("reason"))
                    for v in verdicts if isinstance(v, dict)
                ):
                    evid.add(sid)
            linked += sum(1 for i in ids if str(i) in evid)
            total += len(ids)
        elif system == "p2_rag":
            linked += len(ids)
            total += len(ids)
        else:  # p1: suggested names vs corpus-matched ids
            raw = q.get("raw_names") or []
            linked += len(ids)
            total += len(raw) if raw else len(ids)
    return (linked / total) if total else None


def main() -> None:
    data = json.loads(RESULTS_SRC.read_text(encoding="utf-8"))
    per_query_all = data["per_query_metrics"]

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "evaluation_results.json").write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8"
    )
    if REPORT_SRC.exists():
        (RUN_DIR / "thesis_report.json").write_text(
            REPORT_SRC.read_text(encoding="utf-8"), encoding="utf-8"
        )

    cis: dict = {}
    extra: dict = {"auditability_rubric": AUDITABILITY_RUBRIC, "evidence_link_ratio": {}}
    table_rows: list[str] = []

    for system, label in SYSTEMS.items():
        pq = per_query_all.get(system) or []
        if not pq:
            continue
        p5 = [q["precision_at_5"] for q in pq]
        rr = [q["reciprocal_rank"] for q in pq]
        csr = [q["constraint_satisfaction_rate"] for q in pq]
        cis[system] = {
            "precision_at_5": bootstrap_ci(p5),
            "mrr": bootstrap_ci(rr),
            "csr": bootstrap_ci(csr),
        }
        extra["evidence_link_ratio"][system] = evidence_link_ratio(pq, system)

        for tier in TIERS + ["all"]:
            sel = pq if tier == "all" else [q for q in pq if q["difficulty"] == tier]
            if not sel:
                continue
            cost = [q.get("cost_usd") or 0.0 for q in sel]
            lat = [q["execution_time_ms"] for q in sel]
            table_rows.append(
                f"| {label} | {tier} | {len(sel)} "
                f"| {statistics.fmean([q['precision_at_5'] for q in sel]):.3f} "
                f"| {statistics.fmean([q['reciprocal_rank'] for q in sel]):.3f} "
                f"| {statistics.fmean([q['constraint_satisfaction_rate'] for q in sel]):.3f} "
                f"| {statistics.fmean(lat):.0f} "
                f"| {statistics.fmean(cost):.5f} |"
            )

    (RUN_DIR / "bootstrap_cis.json").write_text(
        json.dumps(cis, indent=2), encoding="utf-8"
    )
    (RUN_DIR / "extra_metrics.json").write_text(
        json.dumps(extra, indent=2), encoding="utf-8"
    )

    # ---- plots ---------------------------------------------------------
    labels = [SYSTEMS[s] for s in SYSTEMS if s in cis]
    keys = [s for s in SYSTEMS if s in cis]

    fig, ax = plt.subplots(figsize=(8, 5))
    width = 0.25
    for i, (metric, title) in enumerate(
        [("precision_at_5", "P@5"), ("mrr", "MRR"), ("csr", "CSR")]
    ):
        means = [cis[s][metric]["mean"] for s in keys]
        errs = [
            (cis[s][metric]["mean"] - cis[s][metric]["lo"],
             cis[s][metric]["hi"] - cis[s][metric]["mean"])
            for s in keys
        ]
        lo = [e[0] for e in errs]
        hi = [e[1] for e in errs]
        x = [j + (i - 1) * width for j in range(len(keys))]
        ax.bar(x, means, width, yerr=[lo, hi], capsize=4, label=title)
    ax.set_xticks(range(len(keys)))
    ax.set_xticklabels(labels)
    ax.set_ylabel("score")
    ax.set_title("Headline metrics per paradigm (95% bootstrap CI)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS / "headline_bars.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    for i, tier in enumerate(TIERS):
        vals = []
        for s in keys:
            sel = [q["precision_at_5"] for q in per_query_all[s] if q["difficulty"] == tier]
            vals.append(statistics.fmean(sel) if sel else 0.0)
        x = [j + (i - 1) * width for j in range(len(keys))]
        ax.bar(x, vals, width, label=tier)
    ax.set_xticks(range(len(keys)))
    ax.set_xticklabels(labels)
    ax.set_ylabel("P@5")
    ax.set_title("P@5 per difficulty tier")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS / "tier_breakdown.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.boxplot(
        [[q["execution_time_ms"] / 1000 for q in per_query_all[s]] for s in keys],
        tick_labels=labels,
    )
    ax.set_ylabel("seconds per query")
    ax.set_title("Latency distribution per paradigm")
    fig.tight_layout()
    fig.savefig(PLOTS / "latency_boxplot.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    means = [
        statistics.fmean([q.get("cost_usd") or 0.0 for q in per_query_all[s]])
        for s in keys
    ]
    ax.bar(labels, means)
    ax.set_ylabel("USD per query (mean)")
    ax.set_title("LLM cost per query per paradigm")
    fig.tight_layout()
    fig.savefig(PLOTS / "cost_per_query.png", dpi=150)
    plt.close(fig)

    # ---- summary table -------------------------------------------------
    header = [
        f"# Benchmark run {datetime.now(timezone.utc).isoformat()}",
        "",
        "Corpus: live pool (10,136 suppliers in Postgres / 10,127 in Milvus).",
        "Provider: OpenAI gpt-4o-mini only; no runtime fallback.",
        "",
        "| Paradigm | Tier | n | P@5 | MRR | CSR | Latency ms | Cost USD |",
        "|----------|------|---|-----|-----|-----|-----------|----------|",
    ]
    (RUN_DIR / "summary_table.md").write_text(
        "\n".join(header + table_rows) + "\n", encoding="utf-8"
    )

    total_cost = sum(
        q.get("cost_usd") or 0.0 for s in keys for q in per_query_all[s]
    )
    print(f"Run dir: {RUN_DIR}")
    print(f"Total LLM spend recorded in metrics: ${total_cost:.4f}")
    print(json.dumps(cis, indent=2))


if __name__ == "__main__":
    main()
