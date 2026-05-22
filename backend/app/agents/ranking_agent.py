"""
app/agents/ranking_agent.py — Multi-factor scoring with LLM explanations.

SCORING WEIGHTS (configurable via settings in production):
  constraint_score: 0.40 (0.50 without proximity)
  semantic_score:   0.25 (0.35 without proximity)
  proximity_score:  0.25 (0.00 without radius constraint)
  completeness:     0.10 (0.15 without proximity)

EXPLAINABILITY:
For each supplier in the top 5, the LLM generates a natural-language
explanation of WHY it was ranked where it was.
This is the "explainable AI" feature of SupplierMind.

MINIMUM SCORE THRESHOLD:
Suppliers with total_score < 0.30 are excluded.
Returning a 30% match is worse than an honest "no results found".
"""

import json
import logging
import time
from typing import Optional

from app.agents.base import BaseAgent
from app.agents.state import AgentState, RankedSupplier, SupplierComplianceResult

logger = logging.getLogger(__name__)

MINIMUM_SCORE = 0.30    # Exclude results below this threshold
MAX_RESULTS = 5          # Return top 5 (Precision@5 metric in evaluation)


EXPLANATION_PROMPT = """You are a procurement advisor explaining a supplier recommendation.

Supplier: {name}
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

Be specific and factual. Do not use generic phrases like "strong candidate".
Return only the explanation text, no JSON."""

class RankingAgent(BaseAgent):
    """
    Scores and ranks compliant suppliers, generates explanations.

    EXPLAINABILITY (thesis requirement):
    Every ranked supplier has a human-readable explanation of its score.
    The explanation references specific facts from the supplier profile.
    This satisfies the "explainable AI" research objective.
    """

    agent_name = "ranking"

    def execute(self, state: AgentState) -> AgentState:
        compliance_results = state.get("compliance_results", [])
        semantic_scores = state.get("semantic_scores", {})
        geo_distances = state.get("geo_distances", {})
        constraints = state.get("parsed_constraints") or {}
        has_radius = bool(constraints.get("location_radius_km"))

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

        # ── Score each supplier ───────────────────────────────────────
        scored: list[tuple[float, SupplierComplianceResult]] = []

        for comp_result in compliance_results:
            sid = comp_result["supplier_id"]
            supplier = supplier_map.get(sid, {})

            constraint_score = comp_result["pass_rate"]
            semantic_score = semantic_scores.get(sid, 0.5)
            proximity_score = self._calculate_proximity_score(
                geo_distances.get(sid),
                constraints.get("location_radius_km"),
            ) if has_radius else None
            completeness_score = self._calculate_completeness(supplier)

            # Weighted total
            if has_radius and proximity_score is not None:
                total = (
                    constraint_score * 0.40
                    + semantic_score * 0.25
                    + proximity_score * 0.25
                    + completeness_score * 0.10
                )
            else:
                total = (
                    constraint_score * 0.50
                    + semantic_score * 0.35
                    + completeness_score * 0.15
                )

            # Penalise hard FAIL constraints (not just pass rate)
            has_hard_fail = any(
                r["status"] == "FAIL" and r.get("confidence", 1.0) > 0.8
                for r in comp_result["compliance_results"]
            )
            if has_hard_fail:
                total *= 0.6  # 40% penalty for confirmed hard fail

            if total >= MINIMUM_SCORE:
                scored.append((total, comp_result))

        # Sort by total score (highest first)
        scored.sort(key=lambda x: x[0], reverse=True)
        top_results = scored[:MAX_RESULTS]

        # ── Generate explanations for top results ─────────────────────
        ranked: list[RankedSupplier] = []
        for rank, (total_score, comp_result) in enumerate(top_results, 1):
            sid = comp_result["supplier_id"]
            supplier = supplier_map.get(sid, {})

            constraint_score = comp_result["pass_rate"]
            semantic_score = semantic_scores.get(sid, 0.5)
            proximity_score = self._calculate_proximity_score(
                geo_distances.get(sid),
                constraints.get("location_radius_km"),
            ) if has_radius else None
            completeness_score = self._calculate_completeness(supplier)

            explanation = self._generate_explanation(
                supplier=supplier,
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
            action="ranking_completed",
            input_summary=f"{len(compliance_results)} candidates scored",
            output_summary=(
                f"Top {len(ranked)} results. "
                f"Scores: {[round(r['total_score'], 2) for r in ranked]}. "
                f"{len(scored) - len(ranked)} below threshold ({MINIMUM_SCORE})."
            ),
            duration_ms=duration_ms,
            reasoning=f"Weights: constraint=0.{'40' if has_radius else '50'}, "
                      f"semantic=0.{'25' if has_radius else '35'}, "
                      f"proximity={'0.25' if has_radius else 'N/A'}, "
                      f"completeness=0.{'10' if has_radius else '15'}",
        )

        state["ranked_suppliers"] = ranked
        state["pipeline_status"] = "completed"
        return state

    def _generate_explanation(
        self,
        supplier: dict,
        comp_result: SupplierComplianceResult,
        constraint_score: float,
        semantic_score: float,
        proximity_score: Optional[float],
        total_score: float,
        geo_distance: Optional[float],
        constraints: dict,
    ) -> str:
        """Generate a human-readable explanation using the LLM."""
        compliance_summary_lines = []
        for r in comp_result["compliance_results"]:
            icon = "✓" if r["status"] == "PASS" else ("~" if r["status"] == "PARTIAL" else "✗")
            compliance_summary_lines.append(f"  {icon} {r['constraint_name']}: {r['reason']}")
        compliance_summary = "\n".join(compliance_summary_lines) or "  No specific constraints checked"

        proximity_line = ""
        if proximity_score is not None and geo_distance is not None:
            proximity_line = f"- Proximity score: {proximity_score:.0%} ({geo_distance:.1f}km away)\n"

        prompt = EXPLANATION_PROMPT.format(
            name=supplier.get("name", "Unknown"),
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
        """
        Convert distance to a 0-1 score.
        Distance = 0km → score = 1.0
        Distance = radius → score = 0.5
        Distance > radius → score penalized but not 0 (handled by compliance)
        """
        if distance_km is None or radius_km is None:
            return None
        if radius_km == 0:
            return 1.0
        # Linear decay: closer = higher score
        score = max(0.0, 1.0 - (distance_km / (radius_km * 2)))
        return score

    def _calculate_completeness(self, supplier: dict) -> float:
        """
        Score based on how complete the supplier profile is.
        Penalises missing data (missing description, no certifications, etc.)
        """
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

    def _fetch_suppliers(self, supplier_ids: list[str]) -> list[dict]:
        """Synchronous wrapper for async DB fetch."""
        import asyncio
        from app.db.repositories.supplier_repo import SupplierRepository
        from app.db.session import AsyncSessionLocal

        async def _fetch():
            async with AsyncSessionLocal() as db:
                repo = SupplierRepository(db)
                suppliers = await repo.get_by_supplier_ids_str(supplier_ids)
                return [
                    {
                        "id": str(s.id),
                        "name": s.name,
                        "description": s.description,
                        "category": s.category,
                        "country": s.country,
                        "city": s.city,
                        "certifications": s.certifications or [],
                        "capacity_value": s.capacity_value,
                        "capacity_unit": s.capacity_unit,
                        "lead_time_days": s.lead_time_days,
                        "website": s.website,
                        "contact_email": s.contact_email,
                    }
                    for s in suppliers
                ]

        try:
            return asyncio.get_event_loop().run_until_complete(_fetch())
        except RuntimeError:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _fetch()).result()
