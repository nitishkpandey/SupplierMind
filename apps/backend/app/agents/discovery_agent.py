"""Hybrid supplier retrieval with tier and benchmark-corpus awareness."""

import json
import logging
import time

from sqlalchemy import Text, func, or_, select

from app.agents.base import BaseAgent
from app.agents.compliance_agent import canonical_cert_key
from app.agents.state import AgentState
from app.db.models import Supplier, SupplierStatus, UserSupplierSave
from app.db.repositories.supplier_repo import SupplierRepository
from app.db.session import SyncSessionLocal

logger = logging.getLogger(__name__)

MIN_RESULTS = 5
MAX_RETRIES = 3
RRF_K = 60
CANDIDATE_HANDOFF_LIMIT = 25
PROTECTED_CHANNEL_LIMIT = 10

# Parser categories that are valid procurement concepts but absent from the
# current synthetic SupplierBench corpus. Expand them to nearby corpus
# categories so structured retrieval does not collapse to zero.
CATEGORY_EXPANSIONS = {
    "tools_hardware": ("tools_hardware", "machinery", "metals", "construction_materials"),
    "office_supplies": ("office_supplies", "electronics", "software_services", "packaging", "textiles"),
}

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
        state.setdefault("benchmark_supplier_ids", [])

        constraints = state.get("parsed_constraints") or {}
        retry_count = state.get("retry_count", 0)
        search_scope = state.get("search_scope", "approved_only")
        user_id = state.get("user_id")
        exclude_pending = state.get("exclude_pending", False)
        allowed_supplier_ids = set(state.get("benchmark_supplier_ids") or [])

        return self._run_search(
            state,
            constraints,
            retry_count,
            search_scope,
            user_id,
            exclude_pending,
            allowed_supplier_ids=allowed_supplier_ids or None,
        )

    def _run_search(
        self, state: AgentState, constraints: dict, retry_count: int, search_scope: str,
        user_id: str, exclude_pending: bool = False,
        allowed_supplier_ids: set[str] | None = None,
    ) -> AgentState:
        start = time.time()

        # ── Step 1: Semantic vector search ───────────────────────
        semantic_ranked: dict[str, int] = {}
        semantic_scores: dict[str, float] = {}

        try:
            from app.core.vector_store import get_vector_store
            vs = get_vector_store()
            query_text = self._build_query_text(constraints, state["raw_query"])
            search_kwargs = {}
            if allowed_supplier_ids is not None:
                search_kwargs["allowed_supplier_ids"] = allowed_supplier_ids
            sem_results = vs.search(query_text, top_k=20, **search_kwargs)

            with SyncSessionLocal() as db:
                valid_ids = self._filter_ids_by_scope(
                    db,
                    [r.supplier_id for r in sem_results],
                    search_scope,
                    user_id,
                    exclude_pending,
                    allowed_supplier_ids=allowed_supplier_ids,
                )
                filtered_results = [r for r in sem_results if r.supplier_id in valid_ids]

                semantic_ranked = {r.supplier_id: i + 1 for i, r in enumerate(filtered_results[:10])}
                semantic_scores = {r.supplier_id: r.similarity_score for r in filtered_results[:10]}
                logger.debug("[discovery] Semantic: %d results (filtered from %d)", len(semantic_ranked), len(sem_results))

        except Exception as e:
            logger.warning("[discovery] Semantic search failed: %s", e)

        # ── Step 2 & 3: Structured + Geospatial (sync DB) ────────
        structured_ranked: dict[str, int] = {}
        fresh_ranked: dict[str, int] = {}
        geo_ranked: dict[str, int] = {}
        geo_distances: dict[str, float] = {}
        tier_assignments: dict[str, str] = {}

        try:
            with SyncSessionLocal() as db:
                # Build base condition for scope
                # approved_only = status=='approved' OR user_supplier_saves matching this user
                # both = status IN ('approved', 'discovered', 'pending_review')
                # unless exclude_pending is set for evaluation.
                base_conds = []
                if search_scope == "approved_only":
                    in_scope_statuses = [SupplierStatus.approved]
                else:
                    in_scope_statuses = [SupplierStatus.approved, SupplierStatus.discovered]
                if search_scope != "approved_only" and not exclude_pending:
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
                category_values = self._category_filter_values(category)
                country = self._extract_country_from_constraints(constraints)
                city = self._extract_city_from_constraints(constraints)
                certs = constraints.get("certifications")
                product_terms = self._product_keyword_terms(constraints)

                has_structured_filters = bool(category_values or country or city or certs or product_terms)
                structured = []
                if has_structured_filters:
                    def fetch_structured(
                        *,
                        city_filter: str | None,
                        keyword_terms: list[str],
                    ) -> list[Supplier]:
                        query = self._build_structured_query(
                            scope_filter=scope_filter,
                            category_values=category_values,
                            country=country,
                            city=city_filter,
                            certs=certs,
                            product_terms=keyword_terms,
                            allowed_supplier_ids=allowed_supplier_ids,
                        )
                        return list(db.execute(query.limit(20)).scalars().all())

                    structured = fetch_structured(
                        city_filter=city,
                        keyword_terms=product_terms,
                    )

                    if not structured and city:
                        structured = fetch_structured(
                            city_filter=None,
                            keyword_terms=product_terms,
                        )

                    if (
                        not structured
                        and len(category_values) > 1
                        and product_terms
                    ):
                        structured = fetch_structured(
                            city_filter=city,
                            keyword_terms=[],
                        )
                        if not structured and city:
                            structured = fetch_structured(
                                city_filter=None,
                                keyword_terms=[],
                            )
                structured_ranked = {str(s.id): i + 1 for i, s in enumerate(structured)}
                logger.debug("[discovery] Structured filter: %d results", len(structured))

                fresh_ids = self._valid_newly_discovered_ids(
                    db=db,
                    ids=state.get("newly_discovered_supplier_ids", []),
                    scope=search_scope,
                    user_id=user_id,
                    exclude_pending=exclude_pending,
                    allowed_supplier_ids=allowed_supplier_ids,
                )
                fresh_ranked = {sid: i + 1 for i, sid in enumerate(fresh_ids)}
                if fresh_ranked:
                    logger.debug(
                        "[discovery] Fresh external candidates carried forward: %d",
                        len(fresh_ranked),
                    )

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
                    geo_ids = [str(s.id) for s, _ in geo_with_dist]
                    valid_geo_ids = self._filter_ids_by_scope(
                        db,
                        geo_ids,
                        search_scope,
                        user_id,
                        exclude_pending,
                        allowed_supplier_ids=allowed_supplier_ids,
                    )
                    valid_geo = [(s, d) for s, d in geo_with_dist if str(s.id) in valid_geo_ids]
                    geo_ranked = {str(s.id): i + 1 for i, (s, _) in enumerate(valid_geo)}
                    geo_distances = {str(s.id): dist for s, dist in valid_geo}
                    logger.debug("[discovery] Geospatial: %d results", len(valid_geo))

                all_found_ids = set(semantic_ranked) | set(structured_ranked) | set(fresh_ranked) | set(geo_ranked)
                if all_found_ids:
                    suppliers_info = db.execute(
                        select(Supplier.id, Supplier.status).where(Supplier.id.in_(all_found_ids))
                    ).all()

                    saved_ids = set()
                    if user_id:
                        saved_ids = set(db.execute(
                            select(UserSupplierSave.supplier_id)
                            .where(UserSupplierSave.supplier_id.in_(all_found_ids))
                            .where(UserSupplierSave.user_id == user_id)
                        ).scalars().all())

                    for sid, status in suppliers_info:
                        sid_str = str(sid)
                        if status == SupplierStatus.approved:
                            tier_assignments[sid_str] = "approved"
                        elif sid in saved_ids:
                            tier_assignments[sid_str] = "saved"
                        elif status == SupplierStatus.pending_review:
                            tier_assignments[sid_str] = "pending_review"
                        else:
                            tier_assignments[sid_str] = "discovered"

        except Exception as e:
            logger.error("[discovery] DB search failed: %s", e)

        # ── Step 4: Merge with Reciprocal Rank Fusion ─────────────────
        all_ids = set(semantic_ranked) | set(structured_ranked) | set(fresh_ranked) | set(geo_ranked)
        rrf_scores: dict[str, float] = {}
        for sid in all_ids:
            score = 0.0
            if sid in semantic_ranked:
                score += 1.0 / (RRF_K + semantic_ranked[sid])
            if sid in structured_ranked:
                score += 1.0 / (RRF_K + structured_ranked[sid])
            if sid in fresh_ranked:
                score += 1.0 / (RRF_K + fresh_ranked[sid])
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
                f"fresh={len(fresh_ranked)}, "
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
                    state,
                    relaxed,
                    retry_count + 1,
                    search_scope,
                    user_id,
                    exclude_pending,
                    allowed_supplier_ids=allowed_supplier_ids,
                )

        # ── Final state ───────────────────────────────────────────────
        selected_candidate_ids = self._candidate_handoff_ids(
            rrf_sorted_ids=candidate_ids,
            structured_ranked=structured_ranked,
            fresh_ranked=fresh_ranked,
            geo_ranked=geo_ranked,
            semantic_ranked=semantic_ranked,
        )
        state["candidate_supplier_ids"] = selected_candidate_ids
        state["semantic_scores"] = {k: v for k, v in semantic_scores.items() if k in selected_candidate_ids}
        state["geo_distances"] = {k: v for k, v in geo_distances.items() if k in selected_candidate_ids}
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

    def _valid_newly_discovered_ids(
        self,
        db,
        ids: list[str],
        scope: str,
        user_id: str,
        exclude_pending: bool = False,
        allowed_supplier_ids: set[str] | None = None,
    ) -> list[str]:
        """Return freshly ingested web supplier IDs that belong in this run.

        External discovery already decided these rows are relevant enough to
        create for the current query. Carry them forward as their own retrieval
        signal so the immediate shortlist does not depend on the vector index
        rediscovering newly inserted rows in the same pipeline pass.
        """
        ordered = [str(sid) for sid in ids if sid]
        if not ordered or scope == "approved_only":
            return []

        valid = self._filter_ids_by_scope(
            db,
            ordered,
            scope,
            user_id,
            exclude_pending,
            allowed_supplier_ids=allowed_supplier_ids,
        )
        return [sid for sid in ordered if sid in valid]

    @staticmethod
    def _candidate_handoff_ids(
        *,
        rrf_sorted_ids: list[str],
        structured_ranked: dict[str, int],
        fresh_ranked: dict[str, int],
        geo_ranked: dict[str, int],
        semantic_ranked: dict[str, int],
    ) -> list[str]:
        """Return a balanced downstream candidate pool.

        A partial vector index can produce stale semantic matches. Protecting
        high-intent channels prevents exact SQL, geo, and fresh web candidates
        from being crowded out before compliance/ranking can score them.
        """
        selected: list[str] = []
        seen: set[str] = set()

        def add(ids: list[str], limit: int | None = None) -> None:
            for sid in ids[:limit]:
                if len(selected) >= CANDIDATE_HANDOFF_LIMIT:
                    return
                if sid in seen:
                    continue
                seen.add(sid)
                selected.append(sid)

        add(list(fresh_ranked), PROTECTED_CHANNEL_LIMIT)
        add(list(geo_ranked), PROTECTED_CHANNEL_LIMIT)
        add(list(structured_ranked), PROTECTED_CHANNEL_LIMIT)
        add(list(semantic_ranked), PROTECTED_CHANNEL_LIMIT)
        add(rrf_sorted_ids)
        return selected[:CANDIDATE_HANDOFF_LIMIT]

    def _filter_ids_by_scope(
        self,
        db,
        sids: list[str],
        scope: str,
        user_id: str,
        exclude_pending: bool = False,
        allowed_supplier_ids: set[str] | None = None,
    ) -> set[str]:
        """Returns subset of IDs that are allowed by the current search scope.

        pending_review is in-scope only for Discover New Suppliers (`both`);
        the eval path passes exclude_pending=True to keep held suppliers out
        of benchmark scoring.
        """
        if not sids:
            return set()

        if allowed_supplier_ids is not None:
            sids = [sid for sid in sids if sid in allowed_supplier_ids]
            if not sids:
                return set()

        base_conds = []
        if scope == "approved_only":
            in_scope_statuses = [SupplierStatus.approved]
        else:
            in_scope_statuses = [SupplierStatus.approved, SupplierStatus.discovered]
        if scope != "approved_only" and not exclude_pending:
            in_scope_statuses.append(SupplierStatus.pending_review)
        base_conds.append(Supplier.status.in_(in_scope_statuses))

        if user_id:
            base_conds.append(
                Supplier.id.in_(
                    select(UserSupplierSave.supplier_id).where(UserSupplierSave.user_id == user_id)
                )
            )

        valid = db.execute(
            select(Supplier.id)
            .where(Supplier.id.in_(sids))
            .where(Supplier.is_active == True)  # noqa: E712
            .where(or_(*base_conds))
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

    @staticmethod
    def _category_filter_values(category: object) -> list[str]:
        """Return exact category plus corpus-compatible related categories."""
        if not isinstance(category, str) or not category.strip():
            return []
        key = category.strip()
        expanded = CATEGORY_EXPANSIONS.get(key, (key,))
        values: list[str] = []
        seen: set[str] = set()
        for value in expanded:
            if value not in seen:
                seen.add(value)
                values.append(value)
        return values

    @staticmethod
    def _build_structured_query(
        *,
        scope_filter,
        category_values: list[str],
        country: str | None,
        city: str | None,
        certs: list[str] | None,
        product_terms: list[str],
        allowed_supplier_ids: set[str] | None = None,
    ):
        query = select(Supplier).where(Supplier.is_active.is_(True)).where(scope_filter)
        if allowed_supplier_ids is not None:
            query = query.where(Supplier.id.in_(allowed_supplier_ids))

        if category_values:
            query = query.where(Supplier.category.in_(category_values))
        if country:
            query = query.where(Supplier.country == country)
        if city:
            query = query.where(Supplier.city.ilike(city))
        if certs:
            for c in certs:
                cert_filters = [
                    func.cast(Supplier.certifications, Text).ilike(f"%{term}%")
                    for term in DiscoveryAgent._cert_search_terms(c)
                ]
                query = query.where(or_(*cert_filters))
        if product_terms:
            term_filters = []
            for term in product_terms:
                pattern = f"%{term}%"
                term_filters.extend([
                    Supplier.name.ilike(pattern),
                    Supplier.description.ilike(pattern),
                    Supplier.category.ilike(pattern),
                ])
            query = query.where(or_(*term_filters))

        return query

    @staticmethod
    def _product_keyword_terms(constraints: dict) -> list[str]:
        """Terms for DB keyword retrieval when embeddings are incomplete."""
        raw_terms = []
        if constraints.get("product_type"):
            raw_terms.append(str(constraints["product_type"]))
        raw_terms.extend(str(term) for term in constraints.get("product_keywords") or [])

        seen = set()
        terms = []
        for term in raw_terms:
            cleaned = " ".join(term.strip().split())
            key = cleaned.casefold()
            if len(cleaned) < 3 or key in seen:
                continue
            seen.add(key)
            terms.append(cleaned)
        return terms[:8]

    @staticmethod
    def _cert_search_terms(cert: object) -> list[str]:
        """Return common stored spellings for a required certification."""
        if not cert:
            return []
        raw = " ".join(str(cert).strip().split())
        canonical = canonical_cert_key(raw) or raw
        variants = {
            raw,
            canonical,
        }
        if canonical == "ISO 9001":
            variants.update({"ISO 9001:2015", "DIN EN ISO 9001"})
        elif canonical == "AS9100":
            variants.update({"AS9100D", "AS 9100"})
        elif canonical == "IATF 16949":
            variants.update({"IATF 16949:2016", "IATF 16949-2016"})
        elif canonical == "TISAX":
            variants.update({"TISAX AL2", "TISAX AL3"})
        elif canonical == "DIN EN 6789":
            variants.update({"ISO 6789", "DIN EN ISO 6789"})
        elif canonical == "BIFMA/ANSI":
            variants.update({"ANSI/BIFMA", "BIFMA ANSI", "ANSI BIFMA"})

        output: list[str] = []
        seen: set[str] = set()
        for value in variants:
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            output.append(value)
        return output

    @staticmethod
    def _extract_city_from_constraints(constraints: dict) -> str | None:
        if constraints.get("location_radius_km"):
            return None
        city = constraints.get("location_city")
        if not isinstance(city, str) or not city.strip():
            return None
        country = constraints.get("location_country")
        if isinstance(country, str) and city.strip().casefold() == country.strip().casefold():
            return None
        return city.strip()

    def _decide_relaxation(
        self,
        constraints: dict,
        result_count: int,
        previous: list[str],
    ) -> tuple[dict | None, str]:
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
