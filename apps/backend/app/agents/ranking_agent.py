"""Multi-factor supplier ranking with deterministic explanations.

The ranker combines compliance, semantic relevance, proximity, completeness,
and supplier tier. Fresh web-discovered suppliers remain visible as
pending-review results in the originating UI query so managers can approve or
reject them without leaving the result context.
"""

import json
import logging
import time
import unicodedata
from typing import Optional

from app.agents.base import BaseAgent
from app.agents.state import AgentState, SupplierComplianceResult
from app.utils.text_normalization import clean_optional_text, clean_text_list

logger = logging.getLogger(__name__)

MINIMUM_SCORE = 0.40        # Suppliers below this score are excluded from visible results
MAX_RESULTS = 5             # Return top 5 (Precision@5 metric in evaluation)
HARD_FAIL_CONFIDENCE = 0.8  # Confidence above which a FAIL triggers the score penalty
HARD_FAIL_PENALTY = 0.60    # Multiply total score by this on confirmed hard fail (40% cut)
TIER_BOOST_APPROVED = 1.05  # Approved supplier score boost
TIER_BOOST_SAVED = 1.03     # User-saved supplier score boost
PROXIMITY_DECAY_FACTOR = 2  # Linear decay: score = 0 at distance = radius × this factor


# ── Template-based explanations ───────────────────────────────────────
# Result explanations are assembled deterministically from the validated
# compliance matrix and supplier data fields — no LLM writes any of it, so no
# number, cert name, or fact can be hallucinated. Every value traces to a
# database field or a verified compliance verdict.

# Constraints whose verdict reason is already a deterministic, data-built string
# in the compliance agent (safe to reuse verbatim). Everything else is a cert,
# which we phrase from scratch so no LLM prose enters the explanation.
_STRUCTURED_CONSTRAINTS = {"capacity", "lead_time", "location_radius", "country", "category"}

# Quote-or-fail flags that mean "claim could not be verified".
_UNVERIFIED_FLAGS = {
    "quote_not_in_source", "quote_too_short",
    "equivalence_unverifiable", "quote_unverifiable",
}

LOW_SEMANTIC_THRESHOLD = 0.5
SCORABLE_PREFERENCES = {"lead_time", "certifications", "capacity"}
UNSUPPORTED_PREFERENCE_CONCERNS = {
    "support_rating": (
        "Support ratings or public reviews were requested, but no verified "
        "support/review evidence is available for this supplier."
    ),
    "pricing": (
        "Pricing was requested, but no verified pricing data is available "
        "for this supplier."
    ),
}


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
        p for p in (
            clean_optional_text(supplier.get("city")),
            clean_optional_text(supplier.get("country")),
        ) if p
    ) or "not specified"
    return {
        "capacity": _format_capacity(
            supplier.get("capacity_value"), supplier.get("capacity_unit") or ""
        ),
        "lead_time": f"{lead} days" if lead is not None else "not specified",
        "certifications": clean_text_list(supplier.get("certifications")),
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


def build_concerns(
    comp_result: dict,
    semantic_score: Optional[float],
    unsupported_preferences: Optional[list[str]] = None,
) -> list[str]:
    """One concern per FAIL/PARTIAL verdict, plus a low-semantic-match note."""
    concerns = [
        _render_verdict_reason(r)
        for r in comp_result.get("compliance_results", [])
        if r.get("status") in ("FAIL", "PARTIAL")
    ]
    if semantic_score is not None and semantic_score < LOW_SEMANTIC_THRESHOLD:
        concerns.append("Limited semantic match to the query")
    for preference in unsupported_preferences or []:
        concern = UNSUPPORTED_PREFERENCE_CONCERNS.get(preference)
        if concern and concern not in concerns:
            concerns.append(concern)
    return concerns


def build_summary(comp_result: dict, concerns: Optional[list[str]] = None) -> str:
    """One deterministic headline sentence from the verdict mix."""
    results = comp_result.get("compliance_results", [])
    n_fail = sum(1 for r in results if r.get("status") == "FAIL")
    if n_fail:
        return f"Partial match; {n_fail} requirement(s) not met."
    if any(r.get("status") == "PARTIAL" for r in results):
        return "Meets core requirements; some criteria need confirmation."
    if concerns:
        return "Meets hard requirements; review the noted evidence gaps."
    return "Meets all specified requirements."


def has_blocking_fail(comp_result: dict) -> bool:
    """True if any compliance verdict for this candidate is FAIL.

    A candidate with any FAIL verdict is hard-excluded from the final result
    set rather than merely score-penalised, so known-non-compliant suppliers
    never surface. PARTIAL still remains eligible because it means "needs
    confirmation", not "known failure".
    """
    return any(
        r.get("status") == "FAIL"
        for r in comp_result.get("compliance_results", [])
    )


def _supplier_id(scored_result: tuple[float, SupplierComplianceResult]) -> str:
    return scored_result[1]["supplier_id"]


def _select_top_results(
    scored: list[tuple[float, SupplierComplianceResult]],
    forced_review_ids: set[str],
    max_results: int = MAX_RESULTS,
) -> list[tuple[float, SupplierComplianceResult]]:
    """Pick top results while keeping fresh pending-review suppliers visible."""
    scored = sorted(scored, key=lambda x: x[0], reverse=True)
    top_results = scored[:max_results]
    top_ids = {_supplier_id(item) for item in top_results}

    missing_review_results = [
        item for item in scored
        if _supplier_id(item) in forced_review_ids and _supplier_id(item) not in top_ids
    ]

    for review_result in missing_review_results:
        if len(top_results) < max_results:
            top_results.append(review_result)
        else:
            replacement_index = next(
                (
                    i for i in range(len(top_results) - 1, -1, -1)
                    if _supplier_id(top_results[i]) not in forced_review_ids
                ),
                None,
            )
            if replacement_index is None:
                break
            top_results[replacement_index] = review_result

        top_results.sort(key=lambda x: x[0], reverse=True)

    return top_results


def build_explanation(
    supplier: dict,
    tier: str,
    comp_result: dict,
    semantic_score: Optional[float],
    unsupported_preferences: Optional[list[str]] = None,
) -> dict:
    """Assemble the full structured explanation. No LLM involved."""
    concerns = build_concerns(comp_result, semantic_score, unsupported_preferences)
    return {
        "match_reasons": build_match_reasons(comp_result),
        "concerns": concerns,
        "facts": build_facts(supplier, tier),
        "summary": build_summary(comp_result, concerns),
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
        requested_city = constraints.get("location_city")
        has_city_focus = bool(requested_city) and not has_radius
        has_location_score = has_radius or has_city_focus
        query_type = constraints.get("query_type", "general")
        ranking_preferences = [
            str(pref)
            for pref in constraints.get("ranking_preferences") or []
            if str(pref) in SCORABLE_PREFERENCES
        ]
        unsupported_preferences = [
            str(pref)
            for pref in constraints.get("unsupported_preferences") or []
            if str(pref) in UNSUPPORTED_PREFERENCE_CONCERNS
        ]
        has_preference_score = bool(ranking_preferences)
        exclude_pending = bool(state.get("exclude_pending", False))
        fresh_review_ids = set(state.get("newly_discovered_supplier_ids") or [])

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
        w_proximity = 0.25 if has_location_score else 0.0
        w_completeness = 0.10

        if query_type == "geographic_priority" and has_location_score:
            w_proximity = 0.40
            w_constraint = 0.30
            w_semantic = 0.20
            w_completeness = 0.10
        elif query_type == "compliance_critical":
            w_constraint = 0.50
            w_semantic = 0.20
            w_proximity = 0.20 if has_location_score else 0.0
            w_completeness = 0.10 if has_location_score else 0.30
        elif query_type == "capability_match":
            w_semantic = 0.40
            w_constraint = 0.30
            w_proximity = 0.20 if has_location_score else 0.0
            w_completeness = 0.10 if has_location_score else 0.30
        elif has_city_focus:
            w_constraint = 0.45
            w_semantic = 0.25
            w_proximity = 0.20
            w_completeness = 0.10
        elif not has_location_score:
            # General without radius
            w_constraint = 0.50
            w_semantic = 0.35
            w_completeness = 0.15

        w_preference = 0.0
        if has_preference_score:
            w_preference = 0.15
            remaining = 1.0 - w_preference
            w_constraint *= remaining
            w_semantic *= remaining
            w_proximity *= remaining
            w_completeness *= remaining

        # ── Score each supplier ───────────────────────────────────────
        scored: list[tuple[float, SupplierComplianceResult]] = []

        excluded_fail = 0
        excluded_pending = 0
        below_threshold = 0
        forced_review_ids: set[str] = set()
        for comp_result in compliance_results:
            sid = comp_result["supplier_id"]
            tier = tier_assignments.get(sid, "discovered")

            if exclude_pending and tier == "pending_review":
                excluded_pending += 1
                continue

            if has_blocking_fail(comp_result):
                excluded_fail += 1
                continue

            supplier = supplier_map.get(sid, {})
            is_fresh_review_candidate = tier == "pending_review" and sid in fresh_review_ids

            constraint_score = comp_result["pass_rate"]
            semantic_score = semantic_scores.get(sid, 0.5)
            if has_radius:
                proximity_score = self._calculate_proximity_score(
                    geo_distances.get(sid),
                    constraints.get("location_radius_km"),
                ) or 0.0
            elif has_city_focus:
                proximity_score = self._calculate_city_score(
                    supplier.get("city"),
                    str(requested_city),
                )
            else:
                proximity_score = 0.0
            completeness_score = self._calculate_completeness(supplier)
            preference_score = self._calculate_preference_score(
                supplier, ranking_preferences
            )

            # Weighted total
            total = (
                constraint_score * w_constraint
                + semantic_score * w_semantic
                + proximity_score * w_proximity
                + completeness_score * w_completeness
                + preference_score * w_preference
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

            if total < MINIMUM_SCORE:
                below_threshold += 1
                continue

            scored.append((total, comp_result))
            if is_fresh_review_candidate:
                forced_review_ids.add(sid)

        top_results = _select_top_results(scored, forced_review_ids)

        # ── Generate explanations for top results ─────────────────────
        ranked: list[dict] = []
        for rank, (total_score, comp_result) in enumerate(top_results, 1):
            sid = comp_result["supplier_id"]
            supplier = supplier_map.get(sid, {})
            tier = tier_assignments.get(sid, "discovered")

            constraint_score = comp_result["pass_rate"]
            semantic_score = semantic_scores.get(sid, 0.5)
            if has_radius:
                proximity_score = self._calculate_proximity_score(
                    geo_distances.get(sid),
                    constraints.get("location_radius_km"),
                )
            elif has_city_focus:
                proximity_score = self._calculate_city_score(
                    supplier.get("city"),
                    str(requested_city),
                )
            else:
                proximity_score = None
            completeness_score = self._calculate_completeness(supplier)
            preference_score = self._calculate_preference_score(
                supplier, ranking_preferences
            )

            # Deterministic, template-based explanation; no LLM text.
            # Stored as a JSON string in the Text column; the API parses it back
            # into a structured object for the frontend.
            explanation = json.dumps(
                build_explanation(
                    supplier,
                    tier,
                    comp_result,
                    semantic_score,
                    unsupported_preferences,
                )
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
                "proximity_score": (
                    round(proximity_score, 4) if proximity_score is not None else None
                ),
                "completeness_score": round(completeness_score, 4),
                "preference_score": round(preference_score, 4),
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
                f"{max(0, len(scored) - len(ranked))} eligible not selected. "
                f"{below_threshold} candidates excluded below score threshold ({MINIMUM_SCORE}). "
                f"{excluded_fail} excluded for FAIL verdict. "
                f"{excluded_pending} pending excluded for eval. "
                f"{len(forced_review_ids)} fresh review candidate(s) kept visible."
            ),
            duration_ms=duration_ms,
            reasoning=f"Dynamic weights: constraint={w_constraint}, "
                      f"semantic={w_semantic}, proximity={w_proximity}, "
                      f"completeness={w_completeness}, preference={w_preference}. "
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

    def _calculate_city_score(self, supplier_city: object, requested_city: str) -> float:
        if not supplier_city or not requested_city:
            return 0.0
        return 1.0 if self._normalise_city(supplier_city) == self._normalise_city(requested_city) else 0.0

    def _calculate_preference_score(
        self, supplier: dict, preferences: list[str]
    ) -> float:
        scores: list[float] = []

        if "lead_time" in preferences:
            lead_time = supplier.get("lead_time_days")
            if lead_time is None:
                scores.append(0.25)
            elif lead_time <= 14:
                scores.append(1.0)
            elif lead_time <= 30:
                scores.append(0.8)
            elif lead_time <= 60:
                scores.append(0.5)
            else:
                scores.append(0.2)

        if "certifications" in preferences:
            cert_count = len(clean_text_list(supplier.get("certifications")))
            scores.append(min(1.0, cert_count / 3))

        if "capacity" in preferences:
            scores.append(0.75 if supplier.get("capacity_value") is not None else 0.25)

        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    @staticmethod
    def _normalise_city(value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        return " ".join(text.casefold().split())

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
