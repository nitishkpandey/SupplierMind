"""
app/evaluation/metrics.py — All evaluation metrics for SupplierMind thesis.

This module is the single source of truth for metric calculations.
All three systems (SupplierMind, Keyword baseline, Manual baseline)
use the same functions so results are directly comparable.

USAGE:
    from app.evaluation.metrics import (
        precision_at_k,
        constraint_satisfaction_rate,
        mean_reciprocal_rank,
        compute_all_metrics,
    )
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class QueryMetrics:
    """
    Metrics for a single query evaluation.
    One instance per (query × system) combination.
    """
    query_id: str
    query_number: int
    difficulty: str                    # "simple" | "medium" | "hard"
    system_name: str                   # "suppliermind" | "keyword" | "manual"
    retrieved_ids: list[str]           # Supplier IDs returned by system
    ground_truth_ids: list[str]        # Correct supplier IDs from benchmark
    precision_at_5: float              # P@5 score (0.0 to 1.0)
    reciprocal_rank: float             # 1/rank of first correct result
    constraint_satisfaction_rate: float  # Average CSR across returned suppliers
    execution_time_ms: int             # How long did this query take?
    compliance_data: Optional[list[dict]] = field(default=None)  # From SupplierMind only
    cost_usd: Optional[float] = field(default=None)        # LLM spend attributed to this call
    raw_names: Optional[list[str]] = field(default=None)   # Names as the model emitted them (P1/P2)
    reasoning: Optional[str] = field(default=None)         # Model-stated reasoning (P1/P2)


@dataclass
class SystemMetrics:
    """
    Aggregated metrics for one system across all 25 queries.
    This is what goes in your thesis results table.
    """
    system_name: str
    query_count: int
    mean_precision_at_5: float
    std_precision_at_5: float
    mean_csr: float
    std_csr: float
    mean_reciprocal_rank: float
    std_mrr: float
    mean_execution_time_ms: float
    std_execution_time_ms: float
    # Breakdown by difficulty
    simple_p5: float
    medium_p5: float
    hard_p5: float


def precision_at_k(
    retrieved: list[str],
    relevant: set[str],
    k: int = 5,
) -> float:
    """
    Fraction of top-k retrieved items that are relevant.

    Args:
        retrieved: Ordered list of supplier IDs returned by the system
        relevant: Set of ground-truth relevant supplier IDs
        k: Cutoff (default 5 for Precision@5)

    Returns:
        Float in [0.0, 1.0]

    Example:
        retrieved = ["A", "X", "B", "Y", "Z"]
        relevant = {"A", "B", "C"}
        precision_at_k(retrieved, relevant, k=5) → 2/5 = 0.4
    """
    if not retrieved:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for r in top_k if r in relevant)
    return hits / k


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    """
    Reciprocal of the rank of the first relevant item.

    Returns:
        1/rank if a relevant item is found in top 5, else 0.0

    Example:
        retrieved = ["X", "Y", "A", "Z", "B"]
        relevant = {"A", "B"}
        First relevant "A" is at position 3 (rank 3)
        reciprocal_rank → 1/3 = 0.333
    """
    for i, item in enumerate(retrieved[:5]):
        if item in relevant:
            return 1.0 / (i + 1)
    return 0.0


def constraint_satisfaction_rate_from_compliance(
    compliance_results: list[dict],
) -> float:
    """
    Calculate CSR from SupplierMind's compliance agent output.

    Args:
        compliance_results: List of SupplierComplianceResult dicts
            from the compliance agent (top 5 suppliers)

    Returns:
        Average CSR across all suppliers (0.0 to 1.0)

    PARTIAL counts as 0.5 (partial satisfaction is better than failure).
    """
    if not compliance_results:
        return 0.0

    supplier_rates = []
    for supplier_result in compliance_results[:5]:
        checks = supplier_result.get("compliance_results", [])
        if not checks:
            supplier_rates.append(1.0)  # No constraints = trivially satisfied
            continue

        total = len(checks)
        satisfied = 0.0
        for check in checks:
            status = check.get("status", "FAIL")
            if status == "PASS":
                satisfied += 1.0
            elif status == "PARTIAL":
                satisfied += 0.5
            # FAIL adds 0
        supplier_rates.append(satisfied / total)

    return statistics.mean(supplier_rates) if supplier_rates else 0.0


def constraint_satisfaction_rate_from_suppliers(
    supplier_records: list[dict],
    constraints: dict,
) -> float:
    """
    Calculate CSR for baseline systems (no compliance agent output).
    Uses direct field comparison — same logic as the compliance agent's
    hard checks, but without LLM reasoning for soft constraints.

    Used for: Keyword baseline, Manual simulation baseline.

    Args:
        supplier_records: List of supplier dicts returned by baseline
        constraints: Parsed constraints dict from the benchmark query

    Returns:
        Average CSR across returned suppliers
    """
    import math

    if not supplier_records or not constraints:
        return 0.0

    def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlng / 2) ** 2
        )
        return R * 2 * math.asin(math.sqrt(a))

    supplier_rates = []
    for supplier in supplier_records[:5]:
        checks = []

        # Category check
        if constraints.get("category") and supplier.get("category"):
            checks.append(
                1.0 if supplier["category"] == constraints["category"] else 0.0
            )

        # Certification checks
        supplier_certs = [c.upper() for c in (supplier.get("certifications") or [])]
        for req_cert in (constraints.get("certifications") or []):
            checks.append(1.0 if req_cert.upper() in supplier_certs else 0.0)

        # Capacity check
        if constraints.get("capacity_min") and constraints.get("capacity_unit"):
            cap = supplier.get("capacity_value")
            unit = supplier.get("capacity_unit", "")
            if cap is None:
                checks.append(0.5)  # Unknown → partial
            elif unit != constraints["capacity_unit"]:
                checks.append(0.5)  # Unit mismatch → partial
            elif cap >= constraints["capacity_min"]:
                checks.append(1.0)
            elif cap >= constraints["capacity_min"] * 0.8:
                checks.append(0.5)  # Within 20% → partial
            else:
                checks.append(0.0)

        # Lead time check
        if constraints.get("lead_time_max_days"):
            lt = supplier.get("lead_time_days")
            if lt is None:
                checks.append(0.5)
            elif lt <= constraints["lead_time_max_days"]:
                checks.append(1.0)
            else:
                checks.append(0.0)

        # Radius check
        if (
            constraints.get("location_lat")
            and constraints.get("location_lng")
            and constraints.get("location_radius_km")
            and supplier.get("latitude")
            and supplier.get("longitude")
        ):
            dist = haversine(
                constraints["location_lat"],
                constraints["location_lng"],
                supplier["latitude"],
                supplier["longitude"],
            )
            if dist <= constraints["location_radius_km"]:
                checks.append(1.0)
            elif dist <= constraints["location_radius_km"] * 1.1:
                checks.append(0.5)
            else:
                checks.append(0.0)

        rate = statistics.mean(checks) if checks else 1.0
        supplier_rates.append(rate)

    return statistics.mean(supplier_rates) if supplier_rates else 0.0


def mean_reciprocal_rank(query_rr_scores: list[float]) -> float:
    """
    Mean of reciprocal rank scores across all queries.

    Args:
        query_rr_scores: List of reciprocal rank scores (one per query)

    Returns:
        MRR in [0.0, 1.0]
    """
    if not query_rr_scores:
        return 0.0
    return statistics.mean(query_rr_scores)


def aggregate_metrics(
    query_metrics: list[QueryMetrics],
    system_name: str,
) -> SystemMetrics:
    """
    Aggregate per-query metrics into system-level metrics.
    This is what goes in the thesis results table.
    """

    def safe_std(values: list[float]) -> float:
        return statistics.stdev(values) if len(values) > 1 else 0.0

    p5_scores = [m.precision_at_5 for m in query_metrics]
    csr_scores = [m.constraint_satisfaction_rate for m in query_metrics]
    rr_scores = [m.reciprocal_rank for m in query_metrics]
    time_scores = [float(m.execution_time_ms) for m in query_metrics]

    # Breakdown by difficulty
    simple = [m.precision_at_5 for m in query_metrics if m.difficulty == "simple"]
    medium = [m.precision_at_5 for m in query_metrics if m.difficulty == "medium"]
    hard = [m.precision_at_5 for m in query_metrics if m.difficulty == "hard"]

    return SystemMetrics(
        system_name=system_name,
        query_count=len(query_metrics),
        mean_precision_at_5=statistics.mean(p5_scores) if p5_scores else 0.0,
        std_precision_at_5=safe_std(p5_scores),
        mean_csr=statistics.mean(csr_scores) if csr_scores else 0.0,
        std_csr=safe_std(csr_scores),
        mean_reciprocal_rank=statistics.mean(rr_scores) if rr_scores else 0.0,
        std_mrr=safe_std(rr_scores),
        mean_execution_time_ms=statistics.mean(time_scores) if time_scores else 0.0,
        std_execution_time_ms=safe_std(time_scores),
        simple_p5=statistics.mean(simple) if simple else 0.0,
        medium_p5=statistics.mean(medium) if medium else 0.0,
        hard_p5=statistics.mean(hard) if hard else 0.0,
    )
