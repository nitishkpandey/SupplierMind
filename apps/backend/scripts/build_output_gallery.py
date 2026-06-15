"""Build the supervisor output gallery from the locked benchmark results.

Side-by-side view of what each paradigm actually returned on five
representative queries (Q1 simple, Q10/Q14 medium, Q23/Q19 hard).
Reads backend/data/evaluation_results.json, resolves supplier IDs to names
via Postgres, writes docs/supervisor/output_gallery.md. No LLM calls.

Run from backend/:
    uv run python scripts/build_output_gallery.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models import Supplier

BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND.parent / "docs" / "supervisor" / "output_gallery.md"
GALLERY_QUERIES = [1, 10, 14, 23, 19]
SYSTEMS = [
    ("p1_singleprompt", "P1 — Single prompt (parametric memory)"),
    ("p2_rag", "P2 — RAG (retrieve top-10, one prompt)"),
    ("suppliermind", "P3 — SupplierMind (agentic, evidence-gated)"),
]


async def fetch_names(ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(Supplier.id, Supplier.name).where(Supplier.id.in_(ids)))
        ).all()
    return {str(r[0]): r[1] for r in rows}


def supplier_lines(rec: dict, names: dict[str, str]) -> list[str]:
    ids = rec.get("retrieved_ids") or []
    if not ids and rec.get("raw_names"):
        return [f"- {n} *(not in corpus)*" for n in rec["raw_names"]]
    if not ids:
        return ["- *(no suppliers returned)*"]
    out = []
    for i in ids:
        out.append(f"- {names.get(str(i), str(i))}")
    return out


def evidence_block(rec: dict, names: dict[str, str]) -> list[str]:
    """P3 per-constraint verdict summary, one supplier per line."""
    out = []
    for c in rec.get("compliance_data") or []:
        sid = str(c.get("supplier_id", ""))
        verdicts = c.get("compliance_results") or []
        passes = sum(1 for v in verdicts if isinstance(v, dict) and v.get("status") == "PASS")
        fails = [
            f"{v.get('constraint_name')}: {v.get('reason')}"
            for v in verdicts
            if isinstance(v, dict) and v.get("status") not in (None, "PASS")
        ]
        line = f"- **{names.get(sid, sid)}** — {passes}/{len(verdicts)} constraints PASS"
        if fails:
            line += "; failed: " + "; ".join(fails[:2])
        out.append(line)
    return out


async def main() -> None:
    data = json.loads((BACKEND / "data" / "evaluation_results.json").read_text(encoding="utf-8"))
    benchmark = json.loads(
        (BACKEND / "data" / "queries_benchmark.json").read_text(encoding="utf-8")
    )
    by_num = {q["query_number"]: q for q in benchmark}
    pq = data["per_query_metrics"]

    all_ids: set[str] = set()
    for sys_key, _ in SYSTEMS:
        for rec in pq.get(sys_key) or []:
            if rec["query_number"] in GALLERY_QUERIES:
                all_ids.update(str(i) for i in rec.get("retrieved_ids") or [])
    names = await fetch_names(all_ids)

    lines = [
        "# Output Gallery — Three Paradigms Side by Side",
        "",
        f"Benchmark run `{data['run_id']}` (GPT-4o-mini, {data['timestamp'][:10]}).",
        "Five representative queries; per paradigm: returned suppliers, the",
        "reasoning/evidence it produced, latency and cost. Built by",
        "`backend/scripts/build_output_gallery.py`, no manual edits to outputs.",
        "",
    ]

    for qn in GALLERY_QUERIES:
        q = by_num[qn]
        lines += [
            "---",
            "",
            f"## Q{qn} ({q['difficulty']}): “{q['raw_query']}”",
            "",
            f"Ground truth: {q['ground_truth_count']} matching supplier(s) in the corpus."
            + (" **No supplier satisfies all constraints — correct answer is the empty set.**"
               if q["ground_truth_count"] == 0 else ""),
            "",
        ]
        for sys_key, label in SYSTEMS:
            rec = next(r for r in pq[sys_key] if r["query_number"] == qn)
            lat_s = rec["execution_time_ms"] / 1000
            cost = rec.get("cost_usd") or 0.0
            lines += [
                f"### {label}",
                "",
                f"*P@5 {rec['precision_at_5']:.2f} · MRR {rec['reciprocal_rank']:.2f} · "
                f"CSR {rec['constraint_satisfaction_rate']:.2f} · {lat_s:.1f}s · ${cost:.4f}*",
                "",
                "**Returned:**",
                *supplier_lines(rec, names),
                "",
            ]
            if sys_key == "suppliermind" and rec.get("compliance_data"):
                lines += ["**Per-constraint verdicts:**", *evidence_block(rec, names), ""]
            reasoning = (rec.get("reasoning") or "").strip()
            if reasoning and sys_key != "suppliermind":
                snippet = reasoning[:600] + ("…" if len(reasoning) > 600 else "")
                lines += ["**Model reasoning:**", "", f"> {snippet}", ""]
        lines += ["**Observation:** _TODO_", ""]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
