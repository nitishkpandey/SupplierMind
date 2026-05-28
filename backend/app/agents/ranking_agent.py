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


EXPLANATION_PROMPT = """You are a procurement advisor explaining a supplier recommendation.

Supplier: {name}
Tier: {tier} (approved=company trusted, saved=your shortlist, discovered=new from web)
Location: {city}, {country}
Category: {category}
Certifications: {certifications}
Capacity: {capacity}
Lead time: {lead_time} days

Constraint check results:
{compliance_summary}

Scores:
- Constraint satisfaction: {constraint_score:.0%}
- Semantic relevance: {semantic_score:.0%}
{proximity_line}
- Overall score: {total_score:.0%}

Write a 2-3 sentence explanation for a procurement manager explaining:
1. Why this supplier is a good match for the query
2. Any concerns or partial matches they should be aware of
3. Briefly acknowledge their tier status if it's 'approved' or 'saved'

Be specific and factual. Do not use generic phrases like "strong candidate".
Return only the explanation text, no JSON."""

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

        for comp_result in compliance_results:
            sid = comp_result["supplier_id"]
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

            explanation = self._generate_explanation(
                supplier=supplier,
                tier=tier,
                comp_result=comp_result,
                constraint_score=constraint_score,
                semantic_score=semantic_score,
                proximity_score=proximity_score,
                total_score=total_score,
                geo_distance=geo_distances.get(sid),
                constraints=constraints,
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
                f"{len(scored) - len(ranked)} below threshold ({MINIMUM_SCORE})."
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

    def _generate_explanation(
        self,
        supplier: dict,
        tier: str,
        comp_result: SupplierComplianceResult,
        constraint_score: float,
        semantic_score: float,
        proximity_score: Optional[float],
        total_score: float,
        geo_distance: Optional[float],
        constraints: dict,
    ) -> str:
        """Generate a human-readable explanation using the LLM."""
        status_icons = {"PASS": "✓", "PARTIAL": "~", "FAIL": "✗"}
        compliance_summary_lines = []
        for r in comp_result["compliance_results"]:
            icon = status_icons.get(r["status"], "✗")
            compliance_summary_lines.append(f"  {icon} {r['constraint_name']}: {r['reason']}")
        compliance_summary = "\n".join(compliance_summary_lines) or "  No specific constraints checked"

        proximity_line = ""
        if proximity_score is not None and geo_distance is not None:
            proximity_line = f"- Proximity score: {proximity_score:.0%} ({geo_distance:.1f}km away)\n"

        prompt = EXPLANATION_PROMPT.format(
            name=supplier.get("name", "Unknown"),
            tier=tier,
            city=supplier.get("city", "Unknown"),
            country=supplier.get("country", "Unknown"),
            category=supplier.get("category", "Unknown"),
            certifications=", ".join(supplier.get("certifications") or []) or "None listed",
            capacity=f"{supplier.get('capacity_value', 'N/A')} {supplier.get('capacity_unit', '')}",
            lead_time=supplier.get("lead_time_days", "N/A"),
            compliance_summary=compliance_summary,
            constraint_score=constraint_score,
            semantic_score=semantic_score,
            proximity_line=proximity_line,
            total_score=total_score,
        )

        try:
            return self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=200,
            ).strip()
        except Exception as e:
            logger.warning("[ranking] Explanation generation failed: %s", e)
            return (
                f"{supplier.get('name', 'This supplier')} scored {total_score:.0%} overall. "
                f"Constraint satisfaction: {constraint_score:.0%}."
            )

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

