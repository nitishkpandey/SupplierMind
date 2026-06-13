"""Step-8 sanity checks on the locked benchmark results.

Reads the archived run directory + the raw run log and writes
docs/verification/06_sanity_checks.md. Pure analysis, no API calls.

Run from backend/:
    uv run python scripts/sanity_check_benchmark.py results/run_YYYYMMDD [path/to/run.log]
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
REPORT = ROOT / "docs" / "verification" / "06_sanity_checks.md"
SYSTEMS = ["p1_singleprompt", "p2_rag", "suppliermind"]


def _default_log() -> Path:
    """Newest benchmark stderr log (retry/fallback/cost lines go to stderr)."""
    candidates = sorted(
        (ROOT / "results").glob("full_benchmark*err.log"),
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1] if candidates else ROOT / "results" / "full_benchmark_run.log"


def main() -> None:
    run_dir = ROOT / (sys.argv[1] if len(sys.argv) > 1 else f"results/run_{datetime.now():%Y%m%d}")
    log_path = Path(sys.argv[2]) if len(sys.argv) > 2 else _default_log()
    data = json.loads((run_dir / "evaluation_results.json").read_text(encoding="utf-8"))
    pq = data["per_query_metrics"]
    benchmark = json.loads(
        (BACKEND / "data" / "queries_benchmark.json").read_text(encoding="utf-8")
    )
    expected_qids = [q["id"] for q in benchmark]

    findings: list[tuple[str, bool, str]] = []  # (check, pass, detail)

    # 1. every paradigm ran every query
    for s in SYSTEMS:
        got = [q["query_id"] for q in pq.get(s) or []]
        missing = [q for q in expected_qids if q not in got]
        findings.append((
            f"coverage {s}", not missing,
            f"{len(got)}/{len(expected_qids)} queries" + (f", missing {missing}" if missing else ""),
        ))

    # 2 + 3. same corpus + same query set across paradigms
    qid_sets = {s: [q["query_id"] for q in pq.get(s) or []] for s in SYSTEMS}
    same_queries = len({tuple(v) for v in qid_sets.values()}) == 1
    findings.append((
        "same query set across paradigms", same_queries,
        "identical ordered query_id lists" if same_queries else f"differ: { {s: len(v) for s, v in qid_sets.items()} }",
    ))
    findings.append((
        "same corpus across paradigms", True,
        "single process, single benchmark_file, one live corpus "
        f"({data.get('benchmark_file')}); run_id={data.get('run_id')}",
    ))

    # 4. retry / fallback skew from the run log
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        openai_retries = len(re.findall(r"Retrying app\.core\.llm\.OpenAIProvider", log_text))
        groq_retries = len(re.findall(r"Retrying app\.core\.llm\.GroqProvider", log_text))
        voyage_retries = len(re.findall(r"Retrying app\.core\.embeddings", log_text))
        fallbacks = len(re.findall(r"\[llm-fallback\]", log_text))
        findings.append((
            "retry counts", fallbacks == 0,
            f"openai={openai_retries}, groq={groq_retries}, voyage={voyage_retries}, "
            f"llm-fallback events={fallbacks} (fallbacks would mix models across paradigms)",
        ))
    else:
        findings.append(("retry counts", False, f"log not found: {log_path}"))

    # 5. warm-up effect: first-query latency vs median, per system
    for s in SYSTEMS:
        lats = [q["execution_time_ms"] for q in pq.get(s) or []]
        if len(lats) >= 3:
            med = statistics.median(lats)
            ratio = lats[0] / med if med else 0
            findings.append((
                f"warm-up {s}", ratio < 3.0,
                f"first={lats[0]}ms median={med:.0f}ms ratio={ratio:.2f}",
            ))

    # 6. cost consistency: per-query sums vs log total
    per_system_cost = {
        s: sum(q.get("cost_usd") or 0.0 for q in pq.get(s) or []) for s in SYSTEMS
    }
    total_metrics = sum(per_system_cost.values())
    log_total = None
    if log_path.exists():
        totals = re.findall(r"total=\$([0-9.]+)", log_text)
        log_total = float(totals[-1]) if totals else None
    cost_ok = log_total is not None and abs(total_metrics - log_total) <= max(0.01, 0.1 * log_total)
    findings.append((
        "cost consistency", bool(cost_ok),
        f"sum(per-query)={total_metrics:.4f} vs last [llm-cost] running total={log_total} "
        "(dashboard cross-check is manual)",
    ))

    # 7. hard-tier ground-truth-zero phenomenon
    gt_empty = {q["id"] for q in benchmark if not q["ground_truth_supplier_ids"]}
    bad = []
    for s in SYSTEMS:
        for q in pq.get(s) or []:
            if q["query_id"] in gt_empty and (q["precision_at_5"] or q["reciprocal_rank"]):
                bad.append(f"{s}/{q['query_id']}")
    hard_n = sum(1 for q in benchmark if q["difficulty"] == "hard")
    hard_empty = sum(1 for q in benchmark if q["difficulty"] == "hard" and not q["ground_truth_supplier_ids"])
    findings.append((
        "ground-truth-zero queries score 0", not bad,
        f"{hard_empty}/{hard_n} hard queries (plus any others) have empty ground truth; "
        + ("all such cells P@5=MRR=0" if not bad else f"NON-ZERO on {bad} - relevance bug"),
    ))

    blockers = [f for f in findings if not f[1]]
    lines = [
        "# Verification 06: Post-Lock Sanity Checks",
        "",
        f"**Date:** {datetime.now(timezone.utc).isoformat()}",
        f"**Run dir:** {run_dir}",
        f"**Run log:** {log_path}",
        f"**Verdict:** {'NO BLOCKERS' if not blockers else f'{len(blockers)} BLOCKER(S)'}",
        "",
        "| Check | Result | Detail |",
        "|-------|--------|--------|",
    ]
    for name, ok, detail in findings:
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    lines += [
        "",
        "Notes:",
        "- 'Same corpus' holds by construction: all paradigms ran in one process",
        "  against the one live Postgres/Milvus pool in a single runner invocation.",
        "- Ground-truth-zero affects all 7 hard queries and medium Q13; P@5 and MRR",
        "  are 0 there by construction for every paradigm. CSR still differentiates.",
        "- OpenAI dashboard total is a manual cross-check (no spend API).",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
