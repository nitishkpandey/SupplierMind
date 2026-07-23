"""
thesis/scripts/probe_p1_curated.py

A targeted probe: does the single-prompt baseline (P1) stop hallucinating if the
query is very clear and fully specified? It runs P1 on maximally curated queries
(which even instruct it to return "exact, real company names") and checks every
returned name against the 10k corpus.

One LLM call per query (needs OPENAI key in apps/backend/.env). No databases.

Run:
    cd apps/backend
    uv run python ../../thesis/scripts/probe_p1_curated.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "apps" / "backend"
sys.path.insert(0, str(BACKEND))

CURATED_QUERIES = [
    "Find five ISO 9001 certified metal suppliers in Germany with production "
    "capacity above 10,000 kg per month and lead time under 30 days. "
    "Give exact, real company names.",
    "List five ISO 22000 certified food ingredient suppliers based in Germany. "
    "Return only exact, real company names that actually exist.",
]


def norm(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


def main() -> None:
    from experiments.paradigm1_singleprompt import run_paradigm1

    names_idx = {norm(s["name"]) for s in json.loads((BACKEND / "data" / "suppliers_synthetic_10k.json").read_text())}

    for q in CURATED_QUERIES:
        print("\nQUERY:", q)
        r = run_paradigm1(q)
        hits = 0
        for n in r.supplier_names:
            ok = norm(n) in names_idx
            hits += ok
            print(f"  {'IN CORPUS' if ok else 'NOT in corpus'}: {n}")
        n = max(1, len(r.supplier_names))
        print(f"  -> corpus matches {hits}/{len(r.supplier_names)}, hallucination {1 - hits / n:.0%}")


if __name__ == "__main__":
    main()
