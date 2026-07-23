"""
thesis/scripts/analyze_abstention.py

Deterministic. NO LLM, NO cost. Scores the Abstention-5 set.

These 5 queries have NO correct answer by design. So precision is meaningless;
what matters is whether each system correctly returns nothing ("abstains")
instead of inventing a supplier. This is the SQuAD-2.0 / Natural-Questions
"no-answer" idea applied to supplier discovery.

Metrics per system:
  correct_abstention_rate  fraction of queries the system returned NOTHING for
  hallucination_rate       fraction where it returned/invented a supplier anyway
  (P1 is scored on invented names; P2/P3 on returned corpus IDs)

Run (after run_10k_benchmark.py --abstention):
    python thesis/scripts/analyze_abstention.py
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    files = sorted(glob.glob(str(ROOT / "thesis" / "results" / "10k_abstention" / "run_*.json")))
    if not files:
        raise SystemExit(
            "No abstention runs found. Run:\n"
            "  uv run python ../../thesis/scripts/run_10k_benchmark.py --p1 --p2 --p3 --abstention"
        )
    runs = [json.loads(Path(f).read_text()) for f in files]
    n_q = runs[0]["query_count"]

    print("=" * 66)
    print(f"Abstention-5 (unsatisfiable queries) — {len(runs)} run(s), {n_q} queries each")
    print("=" * 66)
    print(f"\n{'system':<20}{'correct-abstention':>20}{'hallucination':>16}")
    print("-" * 66)

    for sysname, label in [("suppliermind", "P3 SupplierMind"),
                           ("p2_rag", "P2 RAG"),
                           ("p1_singleprompt", "P1 single-prompt")]:
        total = abstained = invented = 0
        would_clarify = 0
        for r in runs:
            for row in r["per_query_metrics"].get(sysname, []):
                total += 1
                if sysname == "p1_singleprompt":
                    named = bool(row.get("raw_names"))
                    invented += int(named)
                    abstained += int(not named)
                else:
                    got = bool(row.get("retrieved_ids"))
                    invented += int(got)
                    abstained += int(not got)
                if row.get("would_clarify"):
                    would_clarify += 1
        if not total:
            continue
        extra = f"   (wanted to clarify {would_clarify}/{total})" if sysname == "suppliermind" else ""
        print(f"{label:<20}{abstained/total:>19.2f} {invented/total:>15.2f}{extra}")

    print("\nReading: higher correct-abstention = better; RAG cannot abstain (always")
    print("returns its top-k), single-prompt invents names, the agentic gate should")
    print("reject everything and return nothing.")


if __name__ == "__main__":
    main()
