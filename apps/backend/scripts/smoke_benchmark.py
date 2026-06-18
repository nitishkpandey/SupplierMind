"""Step-4 smoke benchmark: 3 queries (one per tier) x 3 paradigms.

Sanity gate before committing credit to the full SupplierBench-25 run.
Queries: Q1 (simple), Q10 (medium), Q23 (hard). Paradigms: P1 single-prompt,
P2 RAG, P3 SupplierMind. Writes docs/verification/03_smoke_benchmark.md.

Run from backend/:
    uv run python scripts/smoke_benchmark.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("smoke_benchmark")

BACKEND = Path(__file__).resolve().parents[1]
REPORT = BACKEND.parent / "docs" / "verification" / "03_smoke_benchmark.md"
QUERY_NUMBERS = [1, 10, 23]
FULL_RUN_QUERIES = 25


async def main() -> None:
    from app.core.cache import InMemoryCache, set_cache_instance
    from app.core.vector_store import create_vector_store, set_vector_store_instance
    from app.db.session import AsyncSessionLocal
    from app.evaluation.runner import (
        _convert_benchmark_constraints,
        _llm_total_cost,
        _load_supplier_name_index,
        run_paradigm_queries,
        run_suppliermind_query,
    )
    from app.evaluation.metrics import precision_at_k

    set_cache_instance(InMemoryCache())
    set_vector_store_instance(create_vector_store())

    benchmark = json.loads(
        (BACKEND / "data" / "queries_benchmark.json").read_text(encoding="utf-8")
    )
    picked = [q for q in benchmark if q["query_number"] in QUERY_NUMBERS]
    assert len(picked) == len(QUERY_NUMBERS), "missing benchmark queries"

    async with AsyncSessionLocal() as db:
        name_index = await _load_supplier_name_index(db)
    logger.info("Name index: %d suppliers", len(name_index))

    rows: list[dict] = []
    failures: list[str] = []
    started = time.time()

    for q in picked:
        raw = q["raw_query"]
        gt = set(q["ground_truth_supplier_ids"])
        constraints = _convert_benchmark_constraints(q["constraints"])
        logger.info("Q%d [%s] %r", q["query_number"], q["difficulty"], raw)

        # P1 + P2
        try:
            async with AsyncSessionLocal() as db:
                pr = await run_paradigm_queries(raw, constraints, db, name_index)
            for system in ("p1_singleprompt", "p2_rag"):
                r = pr[system]
                rows.append({
                    "query": q["query_number"], "tier": q["difficulty"],
                    "paradigm": system, "ids": r["ids"],
                    "p5": precision_at_k(r["ids"], gt, k=5),
                    "latency_ms": r["exec_ms"], "cost_usd": r["cost_usd"],
                    "error": r["error"],
                })
                if r["error"]:
                    failures.append(f"Q{q['query_number']} {system}: {r['error']}")
        except Exception as e:  # noqa: BLE001
            failures.append(f"Q{q['query_number']} P1/P2 crashed: {e!r}")
            raise

        # P3
        try:
            c0 = _llm_total_cost()
            ids, _compliance, ms = await run_suppliermind_query(
                raw, constraints, f"smoke-{q['query_number']}"
            )
            rows.append({
                "query": q["query_number"], "tier": q["difficulty"],
                "paradigm": "p3_suppliermind", "ids": ids,
                "p5": precision_at_k(ids, gt, k=5),
                "latency_ms": ms, "cost_usd": _llm_total_cost() - c0,
                "error": None,
            })
        except Exception as e:  # noqa: BLE001
            failures.append(f"Q{q['query_number']} P3 crashed: {e!r}")
            raise

    total_cost = sum(r["cost_usd"] or 0.0 for r in rows)
    per_paradigm_cost = {}
    for r in rows:
        per_paradigm_cost[r["paradigm"]] = per_paradigm_cost.get(r["paradigm"], 0.0) + (r["cost_usd"] or 0.0)
    projection = total_cost / len(QUERY_NUMBERS) * FULL_RUN_QUERIES

    # Sanity checks
    cells = len(rows)
    all_populated = all(isinstance(r["ids"], list) and r["latency_ms"] is not None for r in rows)
    cost_sum_ok = abs(sum(per_paradigm_cost.values()) - total_cost) < 1e-9

    lines = [
        "# Verification 03: Smoke Benchmark (3 queries x 3 paradigms)",
        "",
        f"**Date:** {datetime.now(timezone.utc).isoformat()}",
        f"**Provider:** OpenAI / gpt-4o-mini (no runtime fallback)",
        f"**Wall time:** {time.time() - started:.0f}s",
        "",
        "| Q | Tier | Paradigm | Returned IDs (count) | P@5 | Latency ms | Cost USD |",
        "|---|------|----------|----------------------|-----|-----------|----------|",
    ]
    for r in rows:
        ids_short = ", ".join(i[:8] for i in r["ids"][:5]) or "(none)"
        lines.append(
            f"| {r['query']} | {r['tier']} | {r['paradigm']} | {ids_short} ({len(r['ids'])}) "
            f"| {r['p5']:.2f} | {r['latency_ms']} | {r['cost_usd']:.6f} |"
        )
    lines += [
        "",
        "## Sanity checks",
        f"- Cells populated: {cells}/9 {'PASS' if cells == 9 and all_populated else 'FAIL'}",
        f"- Crashes: {len(failures)} {'PASS' if not failures else 'FAIL: ' + '; '.join(failures)}",
        f"- Per-paradigm costs sum to total: {'PASS' if cost_sum_ok else 'FAIL'}",
        "",
        "## Cost",
        f"- Smoke run total: ${total_cost:.4f}",
    ]
    for k, v in per_paradigm_cost.items():
        lines.append(f"  - {k}: ${v:.4f}")
    lines += [
        f"- Projected full 25-query run (linear): **${projection:.4f}**",
        "",
        "Note: paradigm errors (if any) are recorded per row; an error row with "
        "an empty ID list still counts as populated output for the gate.",
    ]

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Report: %s", REPORT)
    logger.info("Smoke total $%.4f, projected full run $%.4f", total_cost, projection)
    if failures:
        raise SystemExit("FAILURES:\n" + "\n".join(failures))


if __name__ == "__main__":
    asyncio.run(main())
