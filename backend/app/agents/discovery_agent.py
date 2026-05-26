"""
app/agents/discovery_agent.py — Hybrid supplier retrieval with agentic retry.
Rewritten to use synchronous DB session (no async/event loop conflicts in LangGraph).
"""

import json
import logging
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.agents.state import AgentState
from app.db.session import SyncSessionLocal
from app.db.repositories.supplier_repo import SupplierRepository

logger = logging.getLogger(__name__)

MIN_RESULTS = 5
MAX_RETRIES = 3
RRF_K = 60

RELAXATION_PROMPT = """You are a procurement search optimizer.
A search returned too few results. Decide which ONE constraint to relax.

Constraints: {constraints}
Results found: {count}
Already relaxed: {previous}

Priority for relaxation (relax first to last):
1. location_radius_km — expand the radius
2. lead_time_max_days — increase lead time limit
3. capacity_min — lower the capacity threshold
4. certifications — only remove ONE certification, keep the others

NEVER relax: category (defines the product type)

Return JSON only:
{{
  "relax_constraint": "constraint_name",
  "new_value": null_or_new_value,
  "reasoning": "one sentence"
}}"""


class DiscoveryAgent(BaseAgent):
    """
    Retrieves candidate suppliers using 3 parallel strategies + agentic retry.
    Uses sync DB session to avoid event loop conflicts inside LangGraph.
    """

    agent_name = "discovery"

    def execute(self, state: AgentState) -> AgentState:
        # Ensure defaults
        state.setdefault("candidate_supplier_ids", [])
        state.setdefault("semantic_scores", {})
        state.setdefault("geo_distances", {})
        state.setdefault("relaxed_constraints", [])
        state.setdefault("retry_count", 0)

        constraints = state.get("parsed_constraints") or {}
        retry_count = state.get("retry_count", 0)

        return self._run_search(state, constraints, retry_count)

    def _run_search(self, state: AgentState, constraints: dict, retry_count: int) -> AgentState:
        start = time.time()

        # ── Strategy 1: Semantic vector search ───────────────────────
        semantic_ranked: dict[str, int] = {}
        semantic_scores: dict[str, float] = {}

        try:
            from app.core.vector_store import get_vector_store
            vs = get_vector_store()
            query_text = self._build_query_text(constraints, state["raw_query"])
            sem_results = vs.search(query_text, top_k=10)
            semantic_ranked = {r.supplier_id: i + 1 for i, r in enumerate(sem_results)}
            semantic_scores = {r.supplier_id: r.similarity_score for r in sem_results}
            logger.info("[discovery] Semantic: %d results", len(sem_results))
        except Exception as e:
            logger.warning("[discovery] Semantic search failed: %s", e)

        # ── Strategy 2 & 3: Structured + Geospatial (sync DB) ────────
        structured_ranked: dict[str, int] = {}
        geo_ranked: dict[str, int] = {}
        geo_distances: dict[str, float] = {}

        try:
            with SyncSessionLocal() as db:
                # Strategy 2: Structured SQL filter
                structured = SupplierRepository.filter_by_constraints_sync(
                    db=db,
                    category=constraints.get("category"),
                    country=self._extract_country(constraints),
                    required_certifications=constraints.get("certifications"),
                    min_capacity=constraints.get("capacity_min"),
                    capacity_unit=constraints.get("capacity_unit"),
                    max_lead_time_days=constraints.get("lead_time_max_days"),
                )
                structured_ranked = {str(s.id): i + 1 for i, s in enumerate(structured)}
                logger.info("[discovery] Structured filter: %d results", len(structured))

                # Strategy 3: Geospatial radius
                if (constraints.get("location_lat") and
                    constraints.get("location_lng") and
                    constraints.get("location_radius_km")):
                    geo_with_dist = SupplierRepository.filter_by_radius_sync(
                        db=db,
                        center_lat=constraints["location_lat"],
                        center_lng=constraints["location_lng"],
                        radius_km=constraints["location_radius_km"],
                    )
                    geo_ranked = {str(s.id): i + 1 for i, (s, _) in enumerate(geo_with_dist)}
                    geo_distances = {str(s.id): dist for s, dist in geo_with_dist}
                    logger.info("[discovery] Geospatial: %d results", len(geo_with_dist))

        except Exception as e:
            logger.error("[discovery] DB search failed: %s", e)

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

        candidate_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)
        duration_ms = int((time.time() - start) * 1000)

        logger.info("[discovery] Merged: %d candidates (retry=%d)", len(candidate_ids), retry_count)

        self._log_audit(
            state,
            action=f"search_completed{'_retry' + str(retry_count) if retry_count > 0 else ''}",
            input_summary=f"query={state['raw_query'][:60]}",
            output_summary=(
                f"semantic={len(semantic_ranked)}, "
                f"structured={len(structured_ranked)}, "
                f"geo={len(geo_ranked)}, "
                f"merged={len(candidate_ids)}"
            ),
            duration_ms=duration_ms,
            reasoning=(
                f"RRF merge applied. "
                f"Relaxed: {state.get('relaxed_constraints', [])}"
                if state.get("relaxed_constraints") else "Initial search."
            ),
        )

        # ── Agentic retry ─────────────────────────────────────────────
        if len(candidate_ids) < MIN_RESULTS and retry_count < MAX_RETRIES:
            relaxed, relax_key = self._decide_relaxation(
                constraints,
                len(candidate_ids),
                state.get("relaxed_constraints", []),
            )
            if relaxed is not None and relax_key:
                state["parsed_constraints"] = relaxed
                state["retry_count"] = retry_count + 1
                state["relaxed_constraints"] = state.get("relaxed_constraints", []) + [relax_key]
                logger.info("[discovery] Relaxing %r, retry %d/%d", relax_key, retry_count + 1, MAX_RETRIES)
                return self._run_search(state, relaxed, retry_count + 1)

        # ── Final state ───────────────────────────────────────────────
        state["candidate_supplier_ids"] = candidate_ids[:10]
        state["semantic_scores"] = {k: v for k, v in semantic_scores.items() if k in candidate_ids}
        state["geo_distances"] = {k: v for k, v in geo_distances.items() if k in candidate_ids}
        state["retry_count"] = retry_count

        if not candidate_ids:
            state["pipeline_status"] = "failed"
            state["error"] = (
                "No suppliers found matching your constraints after "
                f"{retry_count} relaxation attempt(s). "
                "Try broadening your search."
            )
        else:
            state["pipeline_status"] = "running"

        return state

    def _build_query_text(self, constraints: dict, raw_query: str) -> str:
        parts = [raw_query]
        if constraints.get("category"):
            parts.append(f"category: {constraints['category']}")
        if constraints.get("certifications"):
            parts.append(f"certifications: {', '.join(constraints['certifications'])}")
        if constraints.get("location_name"):
            parts.append(f"location: {constraints['location_name']}")
        return " | ".join(parts)

    def _extract_country(self, constraints: dict) -> Optional[str]:
        location = constraints.get("location_name", "") or ""
        if "," in location:
            parts = [p.strip() for p in location.split(",")]
            if len(parts) >= 2:
                return parts[-1]
        return None

    def _decide_relaxation(
        self,
        constraints: dict,
        result_count: int,
        previous: list[str],
    ) -> tuple[Optional[dict], str]:
        """Ask LLM which constraint to relax. Returns (relaxed_constraints, key)."""
        available = [
            k for k in ["location_radius_km", "lead_time_max_days", "capacity_min"]
            if k in constraints and k not in previous
        ]

        if not available:
            return None, ""

        try:
            raw = self.llm.complete_json([
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": RELAXATION_PROMPT.format(
                    constraints=json.dumps({k: v for k, v in constraints.items() if v}, default=str),
                    count=result_count,
                    previous=previous,
                )},
            ])
            decision = json.loads(raw)
            key = decision.get("relax_constraint", "")
            new_val = decision.get("new_value")

            if key not in constraints:
                key = available[0]
                new_val = None

            relaxed = dict(constraints)
            if new_val is None:
                relaxed.pop(key, None)
            else:
                relaxed[key] = new_val

            logger.info("[discovery] LLM relaxed %r → %r: %s", key, new_val, decision.get("reasoning"))
            return relaxed, key

        except Exception as e:
            logger.warning("[discovery] Relaxation decision failed: %s. Using fallback.", e)
            key = available[0]
            relaxed = dict(constraints)
            relaxed.pop(key, None)
            return relaxed, key
