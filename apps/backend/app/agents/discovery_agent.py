"""
app/agents/discovery_agent.py — Hybrid supplier retrieval with tier awareness.

PRODUCTION V2 CHANGES:
- Retrieval respects search_scope ("approved_only" vs "both")
- Queries Tier 2 (user-saved) suppliers automatically
- Records tier_assignments in state for downstream ranking boosts
"""

import json
import logging
import time
from typing import Optional
from sqlalchemy import select, or_, and_, func, Text

from app.agents.base import BaseAgent
from app.agents.state import AgentState
from app.db.session import SyncSessionLocal
from app.db.models import Supplier, SupplierStatus, UserSupplierSave
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

NEVER relax: product_type (defines the product)

Return JSON only:
{{
  "relax_constraint": "constraint_name",
  "new_value": null_or_new_value,
  "reasoning": "one sentence"
}}"""


class DiscoveryAgent(BaseAgent):
    """
    Retrieves candidate suppliers using hybrid search + agentic retry.
    Production v2: Tier-aware retrieval.
    """

    agent_name = "discovery"

    def execute(self, state: AgentState) -> AgentState:
        # Ensure defaults
        state.setdefault("candidate_supplier_ids", [])
        state.setdefault("semantic_scores", {})
        state.setdefault("geo_distances", {})
        state.setdefault("relaxed_constraints", [])
        state.setdefault("tier_assignments", {})
        state.setdefault("retry_count", 0)

        constraints = state.get("parsed_constraints") or {}
        retry_count = state.get("retry_count", 0)
        search_scope = state.get("search_scope", "approved_only")
        user_id = state.get("user_id")
        # Sprint A (HITL): pending_review suppliers are in-scope for normal
        # search so the UI can surface them with a badge. The eval path sets
        # exclude_pending=True so benchmark scoring never sees them.
        exclude_pending = state.get("exclude_pending", False)

        return self._run_search(
            state, constraints, retry_count, search_scope, user_id, exclude_pending
        )

    def _run_search(
        self, state: AgentState, constraints: dict, retry_count: int, search_scope: str,
        user_id: str, exclude_pending: bool = False,
    ) -> AgentState:
        start = time.time()

        # ── Step 1: Semantic vector search ───────────────────────
        semantic_ranked: dict[str, int] = {}
        semantic_scores: dict[str, float] = {}

        try:
            from app.core.vector_store import get_vector_store
            vs = get_vector_store()
            query_text = self._build_query_text(constraints, state["raw_query"])
            sem_results = vs.search(query_text, top_k=20) # Get more to filter locally

            # Filter vector results by scope (Milvus doesn't currently index status in this prototype)
            with SyncSessionLocal() as db:
                valid_ids = self._filter_ids_by_scope(db, [r.supplier_id for r in sem_results], search_scope, user_id, exclude_pending)
                filtered_results = [r for r in sem_results if r.supplier_id in valid_ids]

                semantic_ranked = {r.supplier_id: i + 1 for i, r in enumerate(filtered_results[:10])}
                semantic_scores = {r.supplier_id: r.similarity_score for r in filtered_results[:10]}
                logger.debug("[discovery] Semantic: %d results (filtered from %d)", len(semantic_ranked), len(sem_results))

        except Exception as e:
            logger.warning("[discovery] Semantic search failed: %s", e)

        # ── Step 2 & 3: Structured + Geospatial (sync DB) ────────
        structured_ranked: dict[str, int] = {}
        geo_ranked: dict[str, int] = {}
        geo_distances: dict[str, float] = {}
        tier_assignments: dict[str, str] = {}

        try:
            with SyncSessionLocal() as db:
                # Build base condition for scope
                # approved_only = status=='approved' OR user_supplier_saves matching this user
                # both = status IN ('approved', 'discovered') OR user_supplier_saves
                # Sprint A (HITL): pending_review joins the in-scope set so held
                # suppliers appear in normal results — unless exclude_pending is
                # set (the eval path), which keeps the benchmark reproducible.
                base_conds = []
                if search_scope == "approved_only":
                    in_scope_statuses = [SupplierStatus.approved]
                else:
                    in_scope_statuses = [SupplierStatus.approved, SupplierStatus.discovered]
                if not exclude_pending:
                    in_scope_statuses.append(SupplierStatus.pending_review)
                base_conds.append(Supplier.status.in_(in_scope_statuses))

                # Add user saved
                if user_id:
                    base_conds.append(
                        Supplier.id.in_(
                            select(UserSupplierSave.supplier_id).where(UserSupplierSave.user_id == user_id)
                        )
                    )

                scope_filter = or_(*base_conds)

                # Strategy 2: Structured SQL filter
                # We do this manually here to inject the scope filter, since repository method is static
                category = constraints.get("category_hint")
                country = self._extract_country_from_constraints(constraints)
                certs = constraints.get("certifications")

                query = select(Supplier).where(Supplier.is_active == True).where(scope_filter)

                if category:
                    query = query.where(Supplier.category == category)
                if country:
                    query = query.where(Supplier.country == country)
                if certs:
                    for c in certs:
                        query = query.where(func.cast(Supplier.certifications, Text).ilike(f"%{c}%"))

                structured = db.execute(query.limit(20)).scalars().all()
                structured_ranked = {str(s.id): i + 1 for i, s in enumerate(structured)}
                logger.debug("[discovery] Structured filter: %d results", len(structured))

                # Build tier assignments for ALL found suppliers
                all_found_ids = set(semantic_ranked) | set(structured_ranked)
                if all_found_ids:
                    # Determine tiers
                    suppliers_info = db.execute(
                        select(Supplier.id, Supplier.status).where(Supplier.id.in_(all_found_ids))
                    ).all()

                    # Find which ones are saved by user
                    saved_ids = set()
                    if user_id:
                        saved_ids = set(db.execute(
                            select(UserSupplierSave.supplier_id)
                            .where(UserSupplierSave.supplier_id.in_(all_found_ids))
                            .where(UserSupplierSave.user_id == user_id)
                        ).scalars().all())

                    for sid, status in suppliers_info:
                        sid_str = str(sid)
                        # Tier 2 overrides Tier 3, Tier 1 is top
                        if status == SupplierStatus.approved:
                            tier_assignments[sid_str] = "approved"
                        elif sid in saved_ids:
                            tier_assignments[sid_str] = "saved"
                        elif status == SupplierStatus.pending_review:
                            # Sprint A: label honestly so the UI badge is correct;
                            # no tier boost — pending suppliers rank on merit.
                            tier_assignments[sid_str] = "pending_review"
                        else:
                            tier_assignments[sid_str] = "discovered"

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
                    # Filter geo results by scope locally
                    valid_geo = [(s, d) for s, d in geo_with_dist if str(s.id) in tier_assignments]
                    geo_ranked = {str(s.id): i + 1 for i, (s, _) in enumerate(valid_geo)}
                    geo_distances = {str(s.id): dist for s, dist in valid_geo}
                    logger.debug("[discovery] Geospatial: %d results", len(valid_geo))

        except Exception as e:
            logger.error("[discovery] DB search failed: %s", e)

        # ── Step 4: Merge with Reciprocal Rank Fusion ─────────────────
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

        logger.info(
            "[discovery] %d candidates: sem=%d, sql=%d, geo=%d%s",
            len(candidate_ids), len(semantic_ranked), len(structured_ranked), len(geo_ranked),
            f" (retry={retry_count})" if retry_count > 0 else "",
        )

        self._log_audit(
            state,
            action=f"search_completed{'_retry' + str(retry_count) if retry_count > 0 else ''}",
            input_summary=f"query={state['raw_query'][:60]} | scope={search_scope}",
            output_summary=(
                f"semantic={len(semantic_ranked)}, "
                f"structured={len(structured_ranked)}, "
                f"merged={len(candidate_ids)}"
            ),
            duration_ms=duration_ms,
            reasoning=(
                f"RRF merge applied across tiers. "
                f"Relaxed: {state.get('relaxed_constraints', [])}"
                if state.get("relaxed_constraints") else "Initial search."
            ),
        )

        # ── Step 5: Agentic retry ─────────────────────────────────────
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
                return self._run_search(
                    state, relaxed, retry_count + 1, search_scope, user_id, exclude_pending
                )

        # ── Final state ───────────────────────────────────────────────
        state["candidate_supplier_ids"] = candidate_ids[:10]
        state["semantic_scores"] = {k: v for k, v in semantic_scores.items() if k in candidate_ids}
        state["geo_distances"] = {k: v for k, v in geo_distances.items() if k in candidate_ids}
        state["tier_assignments"] = tier_assignments
        state["retry_count"] = retry_count

        if not candidate_ids:
            state["pipeline_status"] = "failed"
            state["error"] = (
                "No suppliers found matching your constraints after "
                f"{retry_count} relaxation attempt(s) in scope '{search_scope}'. "
                "Try broadening your search."
            )
        else:
            state["pipeline_status"] = "running"
            state["error"] = None # Clear any previous error if we succeeded on retry

        return state

    def _filter_ids_by_scope(
        self, db, sids: list[str], scope: str, user_id: str, exclude_pending: bool = False
    ) -> set[str]:
        """Returns subset of IDs that are allowed by the current search scope.

        Sprint A (HITL): pending_review is in-scope for normal search so held
        suppliers surface in the UI; the eval path passes exclude_pending=True
        to keep them out of benchmark scoring.
        """
        if not sids:
            return set()

        base_conds = []
        if scope == "approved_only":
            in_scope_statuses = [SupplierStatus.approved]
        else:
            in_scope_statuses = [SupplierStatus.approved, SupplierStatus.discovered]
        if not exclude_pending:
            in_scope_statuses.append(SupplierStatus.pending_review)
        base_conds.append(Supplier.status.in_(in_scope_statuses))

        if user_id:
            base_conds.append(
                Supplier.id.in_(
                    select(UserSupplierSave.supplier_id).where(UserSupplierSave.user_id == user_id)
                )
            )

        valid = db.execute(
            select(Supplier.id).where(Supplier.id.in_(sids)).where(or_(*base_conds))
        ).scalars().all()

        return {str(i) for i in valid}

    def _build_query_text(self, constraints: dict, raw_query: str) -> str:
        parts = [raw_query]
        if constraints.get("product_type"):
            parts.append(f"product: {constraints['product_type']}")
        if constraints.get("product_keywords"):
            parts.append(f"keywords: {', '.join(constraints['product_keywords'])}")
        if constraints.get("certifications"):
            parts.append(f"certifications: {', '.join(constraints['certifications'])}")
        if constraints.get("location_name"):
            parts.append(f"location: {constraints['location_name']}")
        return " | ".join(parts)

    def _decide_relaxation(
        self,
        constraints: dict,
        result_count: int,
        previous: list[str],
    ) -> tuple[Optional[dict], str]:
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
