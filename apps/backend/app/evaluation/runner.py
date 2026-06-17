"""
app/evaluation/runner.py — SupplierBench evaluation runner.

Runs all 25 benchmark queries through:
1. SupplierMind (full multi-agent pipeline)
2. Baseline A (Keyword SQL)
3. Baseline B (Manual simulation)

Records all metrics and saves to JSON for the thesis results chapter.

HOW TO RUN:
    cd apps/backend
    uv run python scripts/run_evaluation.py

    This takes ~15-20 minutes (SupplierMind queries are ~30s each).
    Progress is printed per query.
    Results saved to: backend/data/evaluation_results.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.evaluation.baselines import keyword_baseline_search, manual_baseline_search
from app.evaluation.metrics import (
    QueryMetrics,
    SystemMetrics,
    aggregate_metrics,
    constraint_satisfaction_rate_from_compliance,
    constraint_satisfaction_rate_from_suppliers,
    precision_at_k,
    reciprocal_rank,
)

logger = logging.getLogger(__name__)

BENCHMARK_FILE = Path(__file__).parent.parent.parent / "data" / "queries_benchmark.json"
RESULTS_FILE = Path(__file__).parent.parent.parent / "data" / "evaluation_results.json"
CHECKPOINT_FILE = Path(__file__).parent.parent.parent / "data" / "evaluation_checkpoint.json"

# Discovery casts user_id to UUID in the user-saves subquery, so the eval must
# pass a real UUID (a non-UUID label raises a SQL error and zeroes every
# candidate set). This nil UUID owns no saves, so it exercises the same path a
# real user would without skewing retrieval.
EVAL_USER_ID = "00000000-0000-0000-0000-000000000000"


async def run_suppliermind_query(
    raw_query: str,
    constraints: dict,
    query_id: str,
) -> tuple[list[str], list[dict], int]:
    """
    Run one query through the full SupplierMind pipeline.

    Returns:
        (list of supplier IDs, compliance_results, execution_time_ms)
    """
    from app.agents.orchestrator import run_pipeline

    start = time.time()
    # Sprint A (HITL): the UI flow includes pending_review suppliers, but the
    # benchmark must not — exclude_pending=True keeps SupplierBench-25
    # reproducible regardless of any pending rows in the DB.
    state = await run_pipeline(
        raw_query, query_id, user_id=EVAL_USER_ID, exclude_pending=True
    )
    exec_ms = int((time.time() - start) * 1000)

    ranked = state.get("ranked_suppliers", [])
    retrieved_ids = [r["supplier_id"] for r in ranked]
    compliance = state.get("compliance_results", [])

    return retrieved_ids, compliance, exec_ms


async def run_baseline_queries(
    raw_query: str,
    constraints: dict,
    db: AsyncSession,
) -> dict:
    """
    Run one query through both baselines.

    Returns:
        Dict with keyword and manual results
    """
    kw_suppliers, kw_ms = await keyword_baseline_search(raw_query, db, top_k=5)
    manual_suppliers, manual_ms = await manual_baseline_search(raw_query, db, top_k=5)

    # Calculate CSR for baselines using direct field comparison
    kw_csr = constraint_satisfaction_rate_from_suppliers(kw_suppliers, constraints)
    manual_csr = constraint_satisfaction_rate_from_suppliers(manual_suppliers, constraints)

    return {
        "keyword": {
            "ids": [s["id"] for s in kw_suppliers],
            "suppliers": kw_suppliers,
            "csr": kw_csr,
            "exec_ms": kw_ms,
        },
        "manual": {
            "ids": [s["id"] for s in manual_suppliers],
            "suppliers": manual_suppliers,
            "csr": manual_csr,
            "exec_ms": manual_ms,
        },
    }


# ── Phase-2 paradigm baselines (Development Plan) ─────────────────────


def _normalise_name(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


async def _load_supplier_name_index(db: AsyncSession) -> dict[str, str]:
    """Map normalised supplier name -> supplier id, for P1 name matching.

    P1 never sees the corpus, so it can only be scored by matching the names
    it suggests against corpus supplier names. Exact-after-normalisation is
    deliberately strict: generous fuzzy matching would flatter the parametric
    baseline.
    """
    from sqlalchemy import select

    from app.db.models import Supplier, SupplierStatus

    # Sprint A: pending_review suppliers are excluded from the P1 name index so
    # the parametric baseline can never be scored against HITL-held rows.
    result = await db.execute(
        select(Supplier.id, Supplier.name).where(
            Supplier.status != SupplierStatus.pending_review
        )
    )
    return {_normalise_name(name): str(sid) for sid, name in result.all() if name}


async def _fetch_supplier_dicts(ids: list[str], db: AsyncSession) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import Supplier, SupplierStatus

    if not ids:
        return []
    # Sprint A: never materialise pending_review suppliers into the P2 corpus,
    # so benchmark scoring stays reproducible even if pending rows exist.
    result = await db.execute(
        select(Supplier).where(
            Supplier.id.in_(ids),
            Supplier.status != SupplierStatus.pending_review,
        )
    )
    rows = {str(s.id): s for s in result.scalars().all()}
    out = []
    for sid in ids:
        s = rows.get(sid)
        if s is None:
            continue
        out.append({
            "id": str(s.id),
            "name": s.name,
            "country": s.country,
            "city": s.city,
            "certifications": list(s.certifications or []),
            "capacity_value": s.capacity_value,
            "capacity_unit": s.capacity_unit,
            "lead_time_days": s.lead_time_days,
            "latitude": s.latitude,
            "longitude": s.longitude,
        })
    return out


def _llm_total_cost() -> float:
    """Process-wide LLM spend so far; used to attribute cost per call."""
    try:
        from app.core.llm import get_llm_client

        return float(get_llm_client().total_cost_usd)
    except Exception:
        return 0.0


async def run_paradigm_queries(
    raw_query: str,
    constraints: dict,
    db: AsyncSession,
    name_index: dict[str, str],
) -> dict:
    """Run one benchmark query through the P1 and P2 baselines.

    Returns the same shape run_baseline_queries uses so the main loop can
    treat all systems uniformly.
    """
    from experiments.paradigm1_singleprompt import run_paradigm1
    from experiments.paradigm2_rag import run_paradigm2

    cost_before = _llm_total_cost()
    p1 = await asyncio.to_thread(run_paradigm1, raw_query)
    p1_cost = _llm_total_cost() - cost_before
    p1_ids = [
        name_index[_normalise_name(n)]
        for n in p1.supplier_names
        if _normalise_name(n) in name_index
    ]
    p1_suppliers = await _fetch_supplier_dicts(p1_ids, db)

    cost_before = _llm_total_cost()
    p2 = await run_paradigm2(raw_query)
    p2_cost = _llm_total_cost() - cost_before
    p2_suppliers = await _fetch_supplier_dicts(p2.supplier_ids, db)

    return {
        "p1_singleprompt": {
            "ids": p1_ids,
            "suppliers": p1_suppliers,
            "csr": constraint_satisfaction_rate_from_suppliers(p1_suppliers, constraints),
            "exec_ms": p1.exec_ms,
            "raw_names": p1.supplier_names,
            "reasoning": "; ".join(p1.reasoning) if p1.reasoning else None,
            "cost_usd": p1_cost,
            "error": p1.error,
        },
        "p2_rag": {
            "ids": p2.supplier_ids,
            "suppliers": p2_suppliers,
            "csr": constraint_satisfaction_rate_from_suppliers(p2_suppliers, constraints),
            "exec_ms": p2.exec_ms,
            "raw_names": p2.supplier_names,
            "reasoning": "; ".join(p2.reasoning) if p2.reasoning else None,
            "cost_usd": p2_cost,
            "error": p2.error,
        },
    }


async def run_full_evaluation(
    run_suppliermind: bool = True,
    run_baselines: bool = True,
    query_limit: int | None = None,
    run_paradigm_baselines: bool = False,
) -> dict:
    """
    Run the complete SupplierBench evaluation.

    Args:
        run_suppliermind: Whether to run SupplierMind (time-consuming, ~15 min)
        run_baselines: Whether to run baselines (fast, ~5 seconds)
        query_limit: Limit number of queries for testing (None = all 25)

    Returns:
        Complete evaluation results dict
    """
    if not BENCHMARK_FILE.exists():
        raise FileNotFoundError(
            f"Benchmark file not found: {BENCHMARK_FILE}\n"
            "Run first: uv run python data/generate_dataset.py"
        )

    with open(BENCHMARK_FILE, encoding="utf-8") as f:
        benchmark_queries = json.load(f)

    if query_limit:
        benchmark_queries = benchmark_queries[:query_limit]

    total = len(benchmark_queries)
    logger.info("=" * 60)
    logger.info("SUPPLIERBENCH EVALUATION")
    logger.info("Queries to evaluate: %d", total)
    logger.info("Systems: %s%s",
                "SupplierMind " if run_suppliermind else "",
                "Keyword Manual" if run_baselines else "")
    logger.info("=" * 60)

    # Per-query results for all systems
    sm_metrics: list[QueryMetrics] = []
    kw_metrics: list[QueryMetrics] = []
    manual_metrics: list[QueryMetrics] = []
    p1_metrics: list[QueryMetrics] = []
    p2_metrics: list[QueryMetrics] = []

    name_index: dict[str, str] = {}
    if run_paradigm_baselines:
        async with AsyncSessionLocal() as db:
            name_index = await _load_supplier_name_index(db)
        logger.info("Loaded %d supplier names for P1 matching", len(name_index))

    for i, query in enumerate(benchmark_queries, 1):
        q_id = query["id"]
        raw_query = query["raw_query"]
        difficulty = query["difficulty"]
        ground_truth_ids = set(query["ground_truth_supplier_ids"])
        constraints = _convert_benchmark_constraints(query["constraints"])

        logger.info(
            "[%d/%d] %s | %r",
            i, total, difficulty.upper(), raw_query[:60]
        )

        # ── Run SupplierMind ──────────────────────────────────────────
        if run_suppliermind:
            logger.info("  Running SupplierMind...")
            try:
                sm_cost_before = _llm_total_cost()
                sm_ids, sm_compliance, sm_ms = await run_suppliermind_query(
                    raw_query, constraints, f"eval-{q_id}"
                )
                sm_cost = _llm_total_cost() - sm_cost_before
                sm_p5 = precision_at_k(sm_ids, ground_truth_ids, k=5)
                sm_rr = reciprocal_rank(sm_ids, ground_truth_ids)
                sm_csr = constraint_satisfaction_rate_from_compliance(sm_compliance)

                sm_metrics.append(QueryMetrics(
                    query_id=q_id,
                    query_number=query["query_number"],
                    difficulty=difficulty,
                    system_name="suppliermind",
                    retrieved_ids=sm_ids,
                    ground_truth_ids=list(ground_truth_ids),
                    precision_at_5=sm_p5,
                    reciprocal_rank=sm_rr,
                    constraint_satisfaction_rate=sm_csr,
                    execution_time_ms=sm_ms,
                    compliance_data=sm_compliance,
                    cost_usd=sm_cost,
                ))
                logger.info(
                    "  SupplierMind: P@5=%.2f CSR=%.2f MRR=%.2f time=%dms",
                    sm_p5, sm_csr, sm_rr, sm_ms
                )
            except Exception as e:
                logger.error("  SupplierMind FAILED: %s", e)
                sm_metrics.append(QueryMetrics(
                    query_id=q_id, query_number=query["query_number"],
                    difficulty=difficulty, system_name="suppliermind",
                    retrieved_ids=[], ground_truth_ids=list(ground_truth_ids),
                    precision_at_5=0.0, reciprocal_rank=0.0,
                    constraint_satisfaction_rate=0.0, execution_time_ms=30000,
                ))

        # ── Run Baselines ─────────────────────────────────────────────
        if run_baselines:
            async with AsyncSessionLocal() as db:
                baseline_results = await run_baseline_queries(raw_query, constraints, db)

            kw_ids = baseline_results["keyword"]["ids"]
            kw_csr = baseline_results["keyword"]["csr"]
            kw_ms = baseline_results["keyword"]["exec_ms"]
            kw_p5 = precision_at_k(kw_ids, ground_truth_ids, k=5)
            kw_rr = reciprocal_rank(kw_ids, ground_truth_ids)

            kw_metrics.append(QueryMetrics(
                query_id=q_id, query_number=query["query_number"],
                difficulty=difficulty, system_name="keyword_sql",
                retrieved_ids=kw_ids, ground_truth_ids=list(ground_truth_ids),
                precision_at_5=kw_p5, reciprocal_rank=kw_rr,
                constraint_satisfaction_rate=kw_csr, execution_time_ms=kw_ms,
            ))

            manual_ids = baseline_results["manual"]["ids"]
            manual_csr = baseline_results["manual"]["csr"]
            manual_ms = baseline_results["manual"]["exec_ms"]
            manual_p5 = precision_at_k(manual_ids, ground_truth_ids, k=5)
            manual_rr = reciprocal_rank(manual_ids, ground_truth_ids)

            manual_metrics.append(QueryMetrics(
                query_id=q_id, query_number=query["query_number"],
                difficulty=difficulty, system_name="manual_simulation",
                retrieved_ids=manual_ids, ground_truth_ids=list(ground_truth_ids),
                precision_at_5=manual_p5, reciprocal_rank=manual_rr,
                constraint_satisfaction_rate=manual_csr, execution_time_ms=manual_ms,
            ))

            logger.info(
                "  Keyword:  P@5=%.2f  |  Manual: P@5=%.2f",
                kw_p5, manual_p5
            )

        # ── Run P1 / P2 paradigm baselines (Development Plan, Phase 3) ──
        if run_paradigm_baselines:
            async with AsyncSessionLocal() as db:
                paradigm_results = await run_paradigm_queries(
                    raw_query, constraints, db, name_index
                )
            for system_name, metrics_list in (
                ("p1_singleprompt", p1_metrics),
                ("p2_rag", p2_metrics),
            ):
                pr = paradigm_results[system_name]
                p5 = precision_at_k(pr["ids"], ground_truth_ids, k=5)
                rr = reciprocal_rank(pr["ids"], ground_truth_ids)
                metrics_list.append(QueryMetrics(
                    query_id=q_id, query_number=query["query_number"],
                    difficulty=difficulty, system_name=system_name,
                    retrieved_ids=pr["ids"], ground_truth_ids=list(ground_truth_ids),
                    precision_at_5=p5, reciprocal_rank=rr,
                    constraint_satisfaction_rate=pr["csr"],
                    execution_time_ms=pr["exec_ms"],
                    cost_usd=pr["cost_usd"],
                    raw_names=pr["raw_names"],
                    reasoning=pr["reasoning"],
                ))
                logger.info(
                    "  %s: P@5=%.2f CSR=%.2f time=%dms%s",
                    system_name, p5, pr["csr"], pr["exec_ms"],
                    f" ERROR={pr['error']}" if pr["error"] else "",
                )

        # A full run takes ~35 min and an interrupted process otherwise loses
        # everything; the checkpoint makes partial results recoverable.
        checkpoint = {
            "completed_queries": i,
            "total_queries": total,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "per_query_metrics": {
                "suppliermind": [asdict(m) for m in sm_metrics],
                "keyword_sql": [asdict(m) for m in kw_metrics],
                "manual_simulation": [asdict(m) for m in manual_metrics],
                "p1_singleprompt": [asdict(m) for m in p1_metrics],
                "p2_rag": [asdict(m) for m in p2_metrics],
            },
        }
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2, default=str)

    # ── Aggregate Results ─────────────────────────────────────────────
    aggregated: dict[str, SystemMetrics] = {}
    if sm_metrics:
        aggregated["suppliermind"] = aggregate_metrics(sm_metrics, "suppliermind")
    if kw_metrics:
        aggregated["keyword_sql"] = aggregate_metrics(kw_metrics, "keyword_sql")
    if manual_metrics:
        aggregated["manual_simulation"] = aggregate_metrics(manual_metrics, "manual_simulation")
    if p1_metrics:
        aggregated["p1_singleprompt"] = aggregate_metrics(p1_metrics, "p1_singleprompt")
    if p2_metrics:
        aggregated["p2_rag"] = aggregate_metrics(p2_metrics, "p2_rag")

    results = {
        "run_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query_count": total,
        "benchmark_file": str(BENCHMARK_FILE),
        "per_query_metrics": {
            "suppliermind": [asdict(m) for m in sm_metrics],
            "keyword_sql": [asdict(m) for m in kw_metrics],
            "manual_simulation": [asdict(m) for m in manual_metrics],
            "p1_singleprompt": [asdict(m) for m in p1_metrics],
            "p2_rag": [asdict(m) for m in p2_metrics],
        },
        "aggregated": {k: asdict(v) for k, v in aggregated.items()},
    }

    # Save results
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    _print_summary(aggregated)
    logger.info("\nResults saved to: %s", RESULTS_FILE)

    return results


def _convert_benchmark_constraints(raw_constraints: dict) -> dict:
    """
    Convert benchmark query constraints to the format expected by metrics functions.
    Benchmark uses "certs" key; our system uses "certifications".
    """
    converted = dict(raw_constraints)
    if "certs" in converted:
        converted["certifications"] = converted.pop("certs")
    if "center" in converted:
        center = converted.pop("center")
        converted["location_lat"] = center[0]
        converted["location_lng"] = center[1]
    if "max_lead" in converted:
        converted["lead_time_max_days"] = converted.pop("max_lead")
    if "min_cap" in converted:
        converted["capacity_min"] = converted.pop("min_cap")
    if "cap_unit" in converted:
        converted["capacity_unit"] = converted.pop("cap_unit")
    return converted


def _print_summary(aggregated: dict[str, SystemMetrics]) -> None:
    """Print a formatted results table to the console."""
    print("\n" + "=" * 80)
    print("EVALUATION RESULTS SUMMARY")
    print("=" * 80)
    print(f"{'System':<25} {'P@5':>8} {'CSR':>8} {'MRR':>8} {'Time(ms)':>12}")
    print("-" * 80)

    order = ["suppliermind", "p2_rag", "p1_singleprompt", "manual_simulation", "keyword_sql"]
    for key in order:
        if key not in aggregated:
            continue
        m = aggregated[key]
        name = {
            "suppliermind": "P3: SupplierMind",
            "p2_rag": "P2: RAG baseline",
            "p1_singleprompt": "P1: Single-prompt LLM",
            "keyword_sql": "Baseline A: Keyword SQL",
            "manual_simulation": "Baseline B: Manual Sim",
        }.get(key, key)
        print(
            f"{name:<25} "
            f"{m.mean_precision_at_5:>8.3f} "
            f"{m.mean_csr:>8.3f} "
            f"{m.mean_reciprocal_rank:>8.3f} "
            f"{m.mean_execution_time_ms:>12.0f}"
        )

    print("=" * 80)

    if "suppliermind" in aggregated:
        sm = aggregated["suppliermind"]
        print("\nSupplierMind breakdown by difficulty:")
        print(f"  Simple queries:  P@5 = {sm.simple_p5:.3f}")
        print(f"  Medium queries:  P@5 = {sm.medium_p5:.3f}")
        print(f"  Hard queries:    P@5 = {sm.hard_p5:.3f}")

    print("=" * 80)
