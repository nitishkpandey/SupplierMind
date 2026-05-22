"""
app/agents/discovery_agent.py — Hybrid supplier retrieval with agentic retry.

THREE RETRIEVAL STRATEGIES (run independently, merged after):
1. Semantic: "What suppliers are semantically similar to this query?" (Milvus)
2. Structured: "What suppliers match these exact SQL constraints?" (PostgreSQL)
3. Geospatial: "What suppliers are within X km of this location?" (Haversine)

MERGE: Reciprocal Rank Fusion (RRF) — rewards suppliers appearing in multiple results.

RETRY LOOP (agentic behavior):
If < MIN_RESULTS found → LLM decides which constraint to relax → retry.
Max MAX_RETRIES attempts. Each retry logged in audit trail.
After MAX_RETRIES, proceed with what we have (even if < 5).
"""

import json
import logging
import time
from typing import Optional

from app.agents.base import BaseAgent
from app.agents.state import AgentState
from app.core.vector_store import get_vector_store

logger = logging.getLogger(__name__)

MIN_RESULTS = 5         # Target minimum candidate count
MAX_RETRIES = 3         # Maximum retry attempts
RRF_K = 60              # Reciprocal Rank Fusion constant (standard value)


RELAXATION_PROMPT = """You are a procurement search optimizer.
A search returned too few results. Decide which constraint to relax.

Constraints used: {constraints}
Results found: {count}
Previous relaxations: {previous}

Rules:
- NEVER relax certifications if they are the primary requirement
- Prefer relaxing: radius first, then lead_time, then capacity, then location
- Never relax category (it defines what product we need)

Return JSON:
{{
  "relax_constraint": "radius" | "lead_time_max_days" | "capacity_min" | "location" | "certifications",
  "new_value": new value for the constraint (null to remove it),
  "reasoning": "one sentence explanation"
}}"""


class DiscoveryAgent(BaseAgent):
    """
    Retrieves candidate suppliers using hybrid search with agentic retry.

    AGENTIC BEHAVIORS:
    1. Tool use: calls 3 different search tools based on what constraints exist
    2. Reflection: counts results, decides if retry is needed
    3. Replanning: asks LLM which constraint to relax on retry
    4. Transparency: every search strategy and retry logged in audit trail
    """

    agent_name = "discovery"

    def execute(self, state: AgentState) -> AgentState:
        if not state.get("candidate_supplier_ids"):
            state["candidate_supplier_ids"] = []
        if not state.get("semantic_scores"):
            state["semantic_scores"] = {}
        if not state.get("geo_distances"):
            state["geo_distances"] = {}
        if not state.get("relaxed_constraints"):
            state["relaxed_constraints"] = []

        constraints = state.get("parsed_constraints") or {}
        retry_count = state.get("retry_count", 0)

        return self._run_search(state, constraints, retry_count)

    def _run_search(
        self,
        state: AgentState,
        constraints: dict,
        retry_count: int,
    ) -> AgentState:
        """Execute one full search cycle with all 3 strategies."""
        start = time.time()

        # Import here to avoid circular imports
        from app.core.vector_store import get_vector_store
        from app.db.repositories.supplier_repo import SupplierRepository
        from app.db.session import AsyncSessionLocal
        import asyncio

        async def _fetch_structured_and_geo():
            async with AsyncSessionLocal() as db:
                repo = SupplierRepository(db)
                structured = await repo.filter_by_constraints(
                    category=constraints.get("category"),
                    country=self._extract_country(constraints),
                    required_certifications=constraints.get("certifications"),
                    min_capacity=constraints.get("capacity_min"),
                    capacity_unit=constraints.get("capacity_unit"),
                    max_lead_time_days=constraints.get("lead_time_max_days"),
                )
                geo_with_dist = []
                if (constraints.get("location_lat") and
                    constraints.get("location_lng") and
                    constraints.get("location_radius_km")):
                    geo_with_dist = await repo.filter_by_radius(
                        center_lat=constraints["location_lat"],
                        center_lng=constraints["location_lng"],
                        radius_km=constraints["location_radius_km"],
                    )
                return structured, geo_with_dist

        # ── Strategy 1: Semantic search ───────────────────────────────
        query_text = self._build_query_text(constraints, state["raw_query"])
        try:
            vs = get_vector_store()
            semantic_results = vs.search(query_text, top_k=20)
            semantic_ranked = {r.supplier_id: i + 1 for i, r in enumerate(semantic_results)}
            semantic_scores = {r.supplier_id: r.similarity_score for r in semantic_results}
            logger.info("[discovery] Semantic search: %d results", len(semantic_results))
        except Exception as e:
            logger.warning("[discovery] Semantic search failed: %s", e)
            semantic_ranked = {}
            semantic_scores = {}

        # ── Strategy 2 & 3: Structured + Geospatial (async) ──────────
        try:
            structured_suppliers, geo_with_dist = asyncio.get_event_loop().run_until_complete(
                _fetch_structured_and_geo()
            )
        except RuntimeError:
            # If we're already in an async context, create new event loop
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _fetch_structured_and_geo())
                structured_suppliers, geo_with_dist = future.result()

        structured_ranked = {
            str(s.id): i + 1 for i, s in enumerate(structured_suppliers)
        }
        logger.info("[discovery] Structured filter: %d results", len(structured_suppliers))

        geo_ranked = {}
        geo_distances = {}
        for i, (supplier, dist_km) in enumerate(geo_with_dist):
            sid = str(supplier.id)
            geo_ranked[sid] = i + 1
            geo_distances[sid] = dist_km
        logger.info("[discovery] Geospatial filter: %d results", len(geo_with_dist))

        # ── Merge with Reciprocal Rank Fusion ─────────────────────────
        all_ids = set(semantic_ranked) | set(structured_ranked) | set(geo_ranked)
        rrf_scores: dict[str, float] = {}
        for sid in all_ids:
            score = 0.0
            if sid in semantic_ranked:
                score += 1.0 / (RRF_K + semantic_ranked[sid])
            if sid in structured_ranked:
                score += 1.0 / (RRF_K + structured_ranked[sid])
            if sid in geo_ranked:
                score += 1.0 / (RRF_K + geo_ranked[sid])
            rrf_scores[sid] = score

        # Sort by RRF score (highest = most relevant across all strategies)
        candidate_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)
        duration_ms = int((time.time() - start) * 1000)

        logger.info(
            "[discovery] Merged results: %d unique candidates (retry=%d)",
            len(candidate_ids), retry_count
        )

        # ── Audit log ─────────────────────────────────────────────────
        self._log_audit(
            state,
            action=f"search_completed{'_retry_' + str(retry_count) if retry_count > 0 else ''}",
            input_summary=f"query={query_text[:60]}...",
            output_summary=(
                f"semantic={len(semantic_ranked)}, "
                f"structured={len(structured_ranked)}, "
                f"geo={len(geo_ranked)}, "
                f"merged={len(candidate_ids)}"
            ),
            duration_ms=duration_ms,
            reasoning=(
                f"RRF merge. Relaxed constraints: {state.get('relaxed_constraints', [])}"
                if state.get("relaxed_constraints") else "Initial search, no relaxations."
            ),
        )

        # ── Agentic retry check ───────────────────────────────────────
        if len(candidate_ids) < MIN_RESULTS and retry_count < MAX_RETRIES:
            logger.info(
                "[discovery] Only %d results (< %d). Attempting constraint relaxation (attempt %d/%d).",
                len(candidate_ids), MIN_RESULTS, retry_count + 1, MAX_RETRIES
            )
            relaxed_constraints, new_constraint_value, relaxation_key = self._decide_relaxation(
                constraints, len(candidate_ids), state.get("relaxed_constraints", [])
            )
            if relaxed_constraints is not None:
                state["parsed_constraints"] = relaxed_constraints
                state["retry_count"] = retry_count + 1
                state["relaxed_constraints"] = state.get("relaxed_constraints", []) + [relaxation_key]
                return self._run_search(state, relaxed_constraints, retry_count + 1)

        # ── Final state update ────────────────────────────────────────
        state["candidate_supplier_ids"] = candidate_ids[:20]  # Cap at 20 for compliance
        state["semantic_scores"] = {k: v for k, v in semantic_scores.items() if k in candidate_ids}
        state["geo_distances"] = {k: v for k, v in geo_distances.items() if k in candidate_ids}
        state["retry_count"] = retry_count

        if len(candidate_ids) == 0:
            state["pipeline_status"] = "failed"
            state["error"] = (
                "No suppliers found matching your constraints. "
                f"Tried relaxing constraints {retry_count} time(s). "
                "Consider broadening your search criteria."
            )
        else:
            state["pipeline_status"] = "running"

        return state

    def _build_query_text(self, constraints: dict, raw_query: str) -> str:
        """
        Build the text used for semantic search.
        Combines raw query with extracted constraints for better embedding quality.
        """
        parts = [raw_query]
        if constraints.get("category"):
            parts.append(f"category: {constraints['category']}")
        if constraints.get("certifications"):
            parts.append(f"certifications: {', '.join(constraints['certifications'])}")
        if constraints.get("location_name"):
            parts.append(f"location: {constraints['location_name']}")
        return " | ".join(parts)

    def _extract_country(self, constraints: dict) -> Optional[str]:
        """
        Try to extract country from location_name.
        "Bremen, Germany" → "Germany"
        "Hamburg" → None (city only, don't filter by country)
        """
        location = constraints.get("location_name", "")
        if not location:
            return None
        # Simple heuristic: if comma in location, last part might be country
        if "," in location:
            parts = [p.strip() for p in location.split(",")]
            if len(parts) >= 2:
                return parts[-1]
        return None

    def _decide_relaxation(
        self,
        constraints: dict,
        result_count: int,
        previous_relaxations: list[str],
    ) -> tuple[Optional[dict], Optional[any], str]:
        """
        Use the LLM to decide which constraint to relax.

        Returns:
            (relaxed_constraints_dict, new_value, relaxed_key)
            or (None, None, "") if no relaxation possible
        """
        # Build constraint summary for LLM
        active = {k: v for k, v in constraints.items() if v is not None}
        available_to_relax = [
            k for k in ["location_radius_km", "lead_time_max_days", "capacity_min"]
            if k in active and k not in previous_relaxations
        ]

        if not available_to_relax:
            logger.warning("[discovery] No constraints left to relax")
            return None, None, ""

        prompt = RELAXATION_PROMPT.format(
            constraints=json.dumps(active, default=str),
            count=result_count,
            previous=previous_relaxations,
        )
        try:
            raw = self.llm.complete_json(
                [
                    {"role": "system", "content": "Return JSON only. No explanation outside JSON."},
                    {"role": "user", "content": prompt},
                ]
            )
            decision = json.loads(raw)
            relax_key = decision.get("relax_constraint", "")
            new_value = decision.get("new_value")

            if relax_key not in active:
                logger.warning("[discovery] LLM suggested unknown constraint: %s", relax_key)
                # Fallback: relax the first available constraint
                relax_key = available_to_relax[0]
                new_value = None

            relaxed = dict(constraints)
            if new_value is None:
                relaxed.pop(relax_key, None)
            else:
                relaxed[relax_key] = new_value

            logger.info(
                "[discovery] Relaxing constraint %r (old=%r → new=%r). Reason: %s",
                relax_key, constraints.get(relax_key), new_value,
                decision.get("reasoning", "")
            )
            self._log_audit(
                {},  # No state here, audit logged separately in _run_search
                action=f"constraint_relaxed_{relax_key}",
                input_summary=f"Too few results ({result_count}). Relaxing {relax_key}",
                output_summary=f"{relax_key}: {constraints.get(relax_key)} → {new_value}",
                duration_ms=0,
                reasoning=decision.get("reasoning"),
            )
            return relaxed, new_value, relax_key

        except Exception as e:
            logger.warning("[discovery] Relaxation decision failed: %s", e)
            # Fallback: remove the first available soft constraint
            relax_key = available_to_relax[0]
            relaxed = dict(constraints)
            relaxed.pop(relax_key, None)
            return relaxed, None, relax_key
