"""Recompute P3 CSR with the same profile-based scorer P1/P2 use.

The runner scores SupplierMind's CSR from the compliance agent's own
verdicts (constraint_satisfaction_rate_from_compliance). That set of
constraints sometimes includes certifications the agent inferred but the
benchmark never asked for, so the published CSR is not comparable to
P1/P2's profile-based CSR. This script re-scores P3's *returned suppliers*
against the *benchmark* constraints using the identical
constraint_satisfaction_rate_from_suppliers function — pure post-processing,
no LLM calls, raw run data untouched.

Writes results/run_YYYYMMDD/csr_harmonized.json and prints a comparison.

Run from backend/:
    uv run python scripts/harmonize_csr.py [results/run_YYYYMMDD]
"""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.db.models import Supplier
from app.db.session import AsyncSessionLocal
from app.evaluation.metrics import constraint_satisfaction_rate_from_suppliers
from app.evaluation.runner import _convert_benchmark_constraints

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
TIERS = ["simple", "medium", "hard"]


async def fetch_supplier_dicts(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    async with AsyncSessionLocal() as db:
        rows = (
            (await db.execute(select(Supplier).where(Supplier.id.in_(ids))))
            .scalars()
            .all()
        )
    by_id = {
        str(s.id): {
            "id": str(s.id),
            "category": s.category,
            "certifications": s.certifications or [],
            "capacity_value": s.capacity_value,
            "capacity_unit": s.capacity_unit,
            "lead_time_days": s.lead_time_days,
            "latitude": s.latitude,
            "longitude": s.longitude,
        }
        for s in rows
    }
    return [by_id[i] for i in ids if i in by_id]


async def main() -> None:
    run_dir = ROOT / (
        sys.argv[1] if len(sys.argv) > 1 else f"results/run_{datetime.now():%Y%m%d}"
    )
    data = json.loads((run_dir / "evaluation_results.json").read_text(encoding="utf-8"))
    benchmark = {
        q["query_number"]: q
        for q in json.loads(
            (BACKEND / "data" / "queries_benchmark.json").read_text(encoding="utf-8")
        )
    }

    per_query = []
    for rec in data["per_query_metrics"]["suppliermind"]:
        qn = rec["query_number"]
        constraints = _convert_benchmark_constraints(benchmark[qn]["constraints"])
        suppliers = await fetch_supplier_dicts([str(i) for i in rec["retrieved_ids"]])
        harmonized = constraint_satisfaction_rate_from_suppliers(suppliers, constraints)
        per_query.append(
            {
                "query_number": qn,
                "difficulty": rec["difficulty"],
                "csr_self_assessed": rec["constraint_satisfaction_rate"],
                "csr_harmonized": harmonized,
                "n_returned": len(rec["retrieved_ids"]),
            }
        )

    def agg(rows: list[dict], key: str) -> float:
        return statistics.mean(r[key] for r in rows) if rows else 0.0

    summary = {
        "definition": (
            "csr_harmonized = constraint_satisfaction_rate_from_suppliers over "
            "P3's returned suppliers vs benchmark constraints — the identical "
            "scorer used for P1/P2/keyword/manual. csr_self_assessed = original "
            "runner value from the compliance agent's own verdicts (may include "
            "agent-inferred constraints absent from the benchmark)."
        ),
        "all": {
            "csr_self_assessed": agg(per_query, "csr_self_assessed"),
            "csr_harmonized": agg(per_query, "csr_harmonized"),
        },
        "per_tier": {
            t: {
                "csr_self_assessed": agg(
                    [r for r in per_query if r["difficulty"] == t], "csr_self_assessed"
                ),
                "csr_harmonized": agg(
                    [r for r in per_query if r["difficulty"] == t], "csr_harmonized"
                ),
            }
            for t in TIERS
        },
        "per_query": per_query,
    }
    out = run_dir / "csr_harmonized.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote {out}\n")
    print(f"{'scope':<10} {'self-assessed':>14} {'harmonized':>12}")
    print(
        f"{'all':<10} {summary['all']['csr_self_assessed']:>14.3f} "
        f"{summary['all']['csr_harmonized']:>12.3f}"
    )
    for t in TIERS:
        row = summary["per_tier"][t]
        print(
            f"{t:<10} {row['csr_self_assessed']:>14.3f} {row['csr_harmonized']:>12.3f}"
        )


if __name__ == "__main__":
    asyncio.run(main())
