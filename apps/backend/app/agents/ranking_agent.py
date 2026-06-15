"""
app/agents/ranking_agent.py — Multi-factor scoring with LLM explanations.

PRODUCTION V2 CHANGES:
- Query-type aware weighting (dynamic weights based on parser classification)
- Tier-based score boosting (Approved * 1.05, Saved * 1.03)
- Severe compliance penalties
- MINIMUM_SCORE raised to 0.40
- Explainability prompt updated to reference tier
"""

import json
import logging
import time
from typing import Optional

from app.agents.base import BaseAgent
from app.agents.state import AgentState, RankedSupplier, SupplierComplianceResult

logger = logging.getLogger(__name__)

MINIMUM_SCORE = 0.40        # Raised for production v2
MAX_RESULTS = 5             # Return top 5 (Precision@5 metric in evaluation)
HARD_FAIL_CONFIDENCE = 0.8  # Confidence above which a FAIL triggers the score penalty
HARD_FAIL_PENALTY = 0.60    # Multiply total score by this on confirmed hard fail (40% cut)
TIER_BOOST_APPROVED = 1.05  # Approved supplier score boost
TIER_BOOST_SAVED = 1.03     # User-saved supplier score boost
PROXIMITY_DECAY_FACTOR = 2  # Linear decay: score = 0 at distance = radius × this factor


# ── Template-based explanations (Task 1.5) ────────────────────────────
# Result explanations are assembled deterministically from the validated
# compliance matrix and supplier data fields — no LLM writes any of it, so no
# number, cert name, or fact can be hallucinated. Every value traces to a
# database field or a verified compliance verdict.

# Constraints whose verdict reason is already a deterministic, data-built string
# in the compliance agent (safe to reuse verbatim). Everything else is a cert,
# which we phrase from scratch so no LLM prose enters the explanation.
_STRUCTURED_CONSTRAINTS = {"capacity", "lead_time", "location_radius", "country", "category"}

# Quote-or-fail flags (Task 1.4) that mean "claim could not be verified".
_UNVERIFIED_FLAGS = {
    "quote_not_in_source", "quote_too_short",
    "equivalence_unverifiable", "quote_unverifiable",
}

LOW_SEMANTIC_THRESHOLD = 0.5


def _render_verdict_reason(r: dict) -> str:
    """Deterministic human phrasing for one constraint verdict.

    Numeric/location/category verdicts reuse the compliance agent's already
    data-built reason string. Cert verdicts are phrased from the verdict status
    alone (never the LLM's free text), so no hallucinated wording survives.
    """
    name = r.get("constraint_name", "")
    status = r.get("status", "FAIL")

    if name in _STRUCTURED_CONSTRAINTS:
        return r.get("reason", f"{name}: {status}")

    # Certification constraint.
    if status == "PASS":
        return f"Holds required {name} certification"
    if status == "PARTIAL":
        if r.get("quote_flag") in _UNVERIFIED_FLAGS:
            return f"{name} could not be verified from supplier text"
        return f"Holds a certification related to {name}, but not an exact match"
    return f"Does not hold required {name} certification"


def _format_capacity(value, unit: str) -> str:
    """Format capacity exactly from the DB value — no rounding, no invention."""
    if value is None:
        return "not specified"
    if isinstance(value, (int, float)) and float(value).is_integer():
        num = f"{int(value):,}"
    elif isinstance(value, (int, float)):
        num = f"{value:,}"
    else:
        num = str(value)
    return f"{num} {unit}".strip() if unit else num


def build_facts(supplier: dict, tier: str) -> dict:
    """Render the supplier's verifiable facts straight from the DB row."""
    lead = supplier.get("lead_time_days")
    location = ", ".join(
        p for p in (supplier.get("city"), supplier.get("country")) if p
    ) or "not specified"
    return {
        "capacity": _format_capacity(
            supplier.get("capacity_value"), supplier.get("capacity_unit") or ""
        ),
        "lead_time": f"{lead} days" if lead is not None else "not specified",
        "certifications": supplier.get("certifications") or [],
        "location": location,
        "tier": tier,
    }


def build_match_reasons(comp_result: dict) -> list[str]:
    """One reason per PASS verdict."""
    return [
        _render_verdict_reason(r)
        for r in comp_result.get("compliance_results", [])
        if r.get("status") == "PASS"
    ]


def build_concerns(comp_result: dict, semantic_score: Optional[float]) -> list[str]:
    """One concern per FAIL/PARTIAL verdict, plus a low-semantic-match note."""
    concerns = [
        _render_verdict_reason(r)
        for r in comp_result.get("compliance_results", [])
        if r.get("status") in ("FAIL", "PARTIAL")
    ]
    if semantic_score is not None and semantic_score < LOW_SEMANTIC_THRESHOLD:
        concerns.append("Limited semantic match to the query")
    return concerns


def build_summary(comp_result: dict) -> str:
    """One deterministic headline sentence from the verdict mix."""
    results = comp_result.get("compliance_results", [])
    n_fail = sum(1 for r in results if r.get("status") == "FAIL")
    if n_fail:
        return f"Partial match; {n_fail} requirement(s) not met."
    if any(r.get("status") == "PARTIAL" for r in results):
        return "Meets core requirements; some criteria need confirmation."
    return "Meets all specified requirements."


def has_blocking_fail(comp_result: dict) -> bool:
    """True if any compliance verdict for this candidate is FAIL.

    Bug 3 (Phase D): a candidate with any FAIL verdict is hard-excluded from the
    final result set rather than merely score-penalised, so known-non-compliant
    suppliers never surface. The check keys on the verdict status itself, so an
    evaluator downgrade to PARTIAL (with reasoning) lifts the block automatically
    — a PARTIAL verdict is not a FAIL.
    """
    return any(
        r.get("status") == "FAIL"
        for r in comp_result.get("compliance_results", [])
    )


def build_explanation(
    supplier: dict, tier: str, comp_result: dict, semantic_score: Optional[float]
) -> dict:
    """Assemble the full structured explanation. No LLM involved."""
    return {
        "match_reasons": build_match_reasons(comp_result),
        "concerns": build_concerns(comp_result, semantic_score),
        "facts": build_facts(supplier, tier),
        "summary": build_summary(comp_result),
    }


class RankingAgent(BaseAgent):
    """
    Scores and ranks compliant suppliers, generates explanations.
    Uses dynamic weights based on query type and boosts scores by tier.
    """

    agent_name = "ranking"

    def execute(self, state: AgentState) -> AgentState:
        compliance_results = state.get("compliance_results", [])
        semantic_scores = state.get("semantic_scores", {})
        geo_distances = state.get("geo_distances", {})
        tier_assignments = state.get("tier_assignments", {})
        constraints = state.get("parsed_constraints") or {}
        has_radius = bool(constraints.get("location_radius_km"))
        query_type = constraints.get("query_type", "general")

        if not compliance_results:
            state["ranked_suppliers"] = []
            state["pipeline_status"] = "completed"
            return state

        start = time.time()

        # ── Fetch supplier details ────────────────────────────────────
        supplier_data = self._fetch_suppliers(
            [r["supplier_id"] for r in compliance_results]
        )
        supplier_map = {s["id"]: s for s in supplier_data}

        # ── Determine dynamic weights ─────────────────────────────────
        w_constraint = 0.40
        w_semantic = 0.25
        w_proximity = 0.25 if has_radius else 0.0
        w_completeness = 0.10

        if query_type == "geographic_priority" and has_radius:
            w_proximity = 0.40
            w_constraint = 0.30
            w_semantic = 0.20
            w_completeness = 0.10
        elif query_type == "compliance_critical":
            w_constraint = 0.50
            w_semantic = 0.20
            w_proximity = 0.20 if has_radius else 0.0
            w_completeness = 0.10 if has_radius else 0.30
        elif query_type == "capability_match":
            w_semantic = 0.40
            w_constraint = 0.30
            w_proximity = 0.20 if has_radius else 0.0
            w_completeness = 0.10 if has_radius else 0.30
        elif not has_radius:
            # General without radius
            w_constraint = 0.50
            w_semantic = 0.35
            w_completeness = 0.15

        # ── Score each supplier ───────────────────────────────────────
        scored: list[tuple[float, SupplierComplianceResult]] = []

        excluded_fail = 0
        for comp_result in compliance_results:
            sid = comp_result["supplier_id"]

            # Bug 3 (Phase D): hard-exclude any candidate with a FAIL verdict.
            if has_blocking_fail(comp_result):
                excluded_fail += 1
                continue

            supplier = supplier_map.get(sid, {})
            tier = tier_assignments.get(sid, "discovered")

            constraint_score = comp_result["pass_rate"]
            semantic_score = semantic_scores.get(sid, 0.5)
            proximity_score = (
                self._calculate_proximity_score(
                    geo_distances.get(sid),
                    constraints.get("location_radius_km"),
                ) or 0.0
            ) if has_radius else 0.0
            completeness_score = self._calculate_completeness(supplier)

            # Weighted total
            total = (
                constraint_score * w_constraint
                + semantic_score * w_semantic
                + proximity_score * w_proximity
                + completeness_score * w_completeness
            )

            # Penalise hard FAIL constraints
            has_hard_fail = any(
                r["status"] == "FAIL" and r.get("confidence", 1.0) > HARD_FAIL_CONFIDENCE
                for r in comp_result["compliance_results"]
            )
            if has_hard_fail:
                total *= HARD_FAIL_PENALTY

            # Tier boosting
            if tier == "approved":
                total = min(1.0, total * TIER_BOOST_APPROVED)
            elif tier == "saved":
                total = min(1.0, total * TIER_BOOST_SAVED)

            if total >= MINIMUM_SCORE:
                scored.append((total, comp_result))

        # Sort by total score (highest first)
        scored.sort(key=lambda x: x[0], reverse=True)
        top_results = scored[:MAX_RESULTS]

        # ── Generate explanations for top results ─────────────────────
        ranked: list[dict] = []
        for rank, (total_score, comp_result) in enumerate(top_results, 1):
            sid = comp_result["supplier_id"]
            supplier = supplier_map.get(sid, {})
            tier = tier_assignments.get(sid, "discovered")

            constraint_score = comp_result["pass_rate"]
            semantic_score = semantic_scores.get(sid, 0.5)
            proximity_score = self._calculate_proximity_score(
                geo_distances.get(sid),
                constraints.get("location_radius_km"),
            ) if has_radius else None
            completeness_score = self._calculate_completeness(supplier)

            # Task 1.5: deterministic, template-based explanation — no LLM.
            # Stored as a JSON string in the Text column; the API parses it back
            # into a structured object for the frontend.
            explanation = json.dumps(
                build_explanation(supplier, tier, comp_result, semantic_score)
            )

            compliance_matrix = {
                r["constraint_name"]: r["status"]
                for r in comp_result["compliance_results"]
            }

            ranked.append({
                "rank": rank,
                "supplier_id": sid,
                "tier": tier,
                "total_score": round(total_score, 4),
                "constraint_score": round(constraint_score, 4),
                "semantic_score": round(semantic_score, 4),
                "proximity_score": round(proximity_score, 4) if proximity_score else None,
                "completeness_score": round(completeness_score, 4),
                "compliance_matrix": compliance_matrix,
                "explanation": explanation,
                "distance_km": round(geo_distances[sid], 2) if sid in geo_distances else None,
            })

        duration_ms = int((time.time() - start) * 1000)
        self._log_audit(
            state,
            action="ranking_completed_v2",
            input_summary=f"{len(compliance_results)} candidates scored (type: {query_type})",
            output_summary=(
                f"Top {len(ranked)} results. "
                f"Scores: {[round(r['total_score'], 2) for r in ranked]}. "
                f"{len(scored) - len(ranked)} below threshold ({MINIMUM_SCORE}). "
                f"{excluded_fail} excluded for FAIL verdict."
            ),
            duration_ms=duration_ms,
            reasoning=f"Dynamic weights: constraint={w_constraint}, "
                      f"semantic={w_semantic}, proximity={w_proximity}, completeness={w_completeness}. "
                      f"Applied tier boosts.",
        )

        logger.info(
            "[ranking] %d ranked, scores: %s",
            len(ranked),
            [round(r["total_score"], 2) for r in ranked],
        )
        state["ranked_suppliers"] = ranked
        # Don't set pipeline_status to completed here, let evaluator do it
        return state

    def _calculate_proximity_score(
        self, distance_km: Optional[float], radius_km: Optional[float]
    ) -> Optional[float]:
        if distance_km is None or radius_km is None:
            return None
        if radius_km == 0:
            return 1.0
        return max(0.0, 1.0 - (distance_km / (radius_km * PROXIMITY_DECAY_FACTOR)))

    def _calculate_completeness(self, supplier: dict) -> float:
        fields = [
            "description", "category", "country", "city",
            "certifications", "capacity_value", "lead_time_days",
            "website", "contact_email",
        ]
        filled = sum(
            1 for f in fields
            if supplier.get(f) not in (None, [], "", 0)
        )
        return filled / len(fields)

