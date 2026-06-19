"""Discover new suppliers from external sources and hold them for review."""

import logging
import time
import uuid
from typing import Optional

from app.agents.base import BaseAgent
from app.agents.state import AgentState
from app.core.config import settings
from app.core.vector_store import get_vector_store
from app.db.models import Supplier, SupplierStatus
from app.db.session import SyncSessionLocal
from app.services.location_enrichment import VerifiedLocation, get_location_enrichment_service
from app.services.sanctions import get_sanctions_service
from app.services.supplier_extraction import SupplierExtractionService
from app.services.web_search import get_web_search_service

logger = logging.getLogger(__name__)


class ExternalDiscoveryAgent(BaseAgent):
    """
    Discovers new suppliers from web sources using two-stage extraction.
    Stage 1: Cheap classification (is this a supplier?)
    Stage 2: Rich extraction from full page content with citations
    """

    agent_name = "external_discovery"

    def __init__(self) -> None:
        super().__init__()
        self.web_search = get_web_search_service()
        self.sanctions = get_sanctions_service()
        self.extractor = SupplierExtractionService()
        self.location_enricher = get_location_enrichment_service()

    def execute(self, state: AgentState) -> AgentState:
        start = time.time()

        state.setdefault("newly_discovered_supplier_ids", [])
        state.setdefault("external_discovery_stats", {})

        if not settings.ENABLE_EXTERNAL_DISCOVERY:
            self._log_audit(
                state,
                action="skipped_disabled",
                input_summary="External discovery disabled in config",
                output_summary="Skipped",
                duration_ms=0,
            )
            return state

        if not self.web_search.is_available:
            logger.warning("[external_discovery] Tavily not configured — skipping")
            self._log_audit(
                state,
                action="skipped_no_api_key",
                input_summary="TAVILY_API_KEY not set",
                output_summary="Skipping external discovery",
                duration_ms=0,
            )
            return state

        constraints = state.get("parsed_constraints") or {}

        # ── Step 1: Web search ───────────────────────────────────────
        max_web_results = max(settings.EXTERNAL_DISCOVERY_MAX_RESULTS, 10)
        web_results = self.web_search.search_suppliers(
            category=constraints.get("category_hint") or constraints.get("category"),
            country=self._extract_country_from_constraints(constraints),
            city=constraints.get("location_city"),
            certifications=constraints.get("certifications"),
            product_terms=self._product_terms_from_constraints(constraints),
            raw_query=state.get("raw_query"),
            max_results=max_web_results,
        )

        logger.info("[external_discovery] Web search: %d candidates", len(web_results))

        if not web_results:
            self._log_audit(
                state,
                action="no_web_results",
                input_summary=(
                    f"category={constraints.get('category_hint')}, "
                    f"country={self._extract_country_from_constraints(constraints)}"
                ),
                output_summary="0 web results from Tavily",
                duration_ms=int((time.time() - start) * 1000),
            )
            return state

        # ── Step 2: Two-stage extraction ─────────────────────────────
        stage1_passed = 0
        stage1_rejected = 0
        extracted: list[dict] = []

        for result in web_results:
            # Stage 1: Cheap classification
            classification = self.extractor.stage1_classify(
                title=result.title,
                url=result.url,
                snippet=result.snippet,
            )

            if not classification.get("is_supplier") or classification.get("confidence", 0) < 0.5:
                stage1_rejected += 1
                logger.debug(
                    "[external_discovery] Stage 1 rejected: %s (%s)",
                    result.url, classification.get("rejection_reason"),
                )
                continue

            stage1_passed += 1

            # Stage 2: Rich extraction from full page
            data = self.extractor.stage2_extract(url=result.url)
            if data:
                extracted.append(data)
                logger.debug("[external_discovery] Extracted: %r", data["name"])

        logger.debug(
            "[external_discovery] Stage 1: %d passed, %d rejected. Stage 2: %d extracted.",
            stage1_passed, stage1_rejected, len(extracted)
        )

        # ── Step 3: Sanctions screening + deduplication ──────────────
        validated: list[dict] = []
        rejected_sanctions = 0
        rejected_duplicate = 0
        rejected_missing_location = 0
        pending_sanctions = 0

        with SyncSessionLocal() as db:
            for s in extracted:
                location = self.location_enricher.enrich(s, constraints)
                if location is None:
                    logger.info(
                        "[external_discovery] Missing verified location: %r",
                        s["name"],
                    )
                    rejected_missing_location += 1
                    continue
                self._apply_verified_location(s, location)

                screening = self.sanctions.screen_company(s["name"])
                if screening.status == "flagged":
                    logger.warning(
                        "[external_discovery] REJECTED (sanctions): %s — lists: %s",
                        s["name"], screening.matched_lists,
                    )
                    rejected_sanctions += 1
                    continue

                if screening.status == "pending_review":
                    # Screening couldn't complete (API rate-limited/down). Do NOT
                    # silently pass as clean — admit the supplier but flag it for
                    # manual review so the UI never claims "sanctions: clear".
                    citations = s.setdefault("source_citations", {}) or {}
                    citations["sanctions"] = {
                        "status": "pending_review",
                        "reason": screening.reason,
                    }
                    s["source_citations"] = citations
                    pending_sanctions += 1

                if self._is_duplicate(db, s["name"], s.get("country")):
                    logger.debug("[external_discovery] Duplicate: %r", s["name"])
                    rejected_duplicate += 1
                    continue

                validated.append(s)

        logger.debug(
            "[external_discovery] Validated %d (rejected: %d sanctions, %d duplicates)",
            len(validated), rejected_sanctions, rejected_duplicate,
        )

        # ── Step 4: Ingest into PostgreSQL + Milvus ──────────────────
        newly_added_ids = []
        if validated:
            newly_added_ids = self._ingest_suppliers(validated)

        # ── Update state ──────────────────────────────────────────────
        state["newly_discovered_supplier_ids"] = newly_added_ids
        state["external_discovery_stats"] = {
            "web_results": len(web_results),
            "stage1_passed": stage1_passed,
            "stage1_rejected": stage1_rejected,
            "extracted": len(extracted),
            "validated": len(validated),
            "rejected_sanctions": rejected_sanctions,
            "pending_sanctions": pending_sanctions,
            "rejected_duplicates": rejected_duplicate,
            "rejected_missing_location": rejected_missing_location,
            "ingested": len(newly_added_ids),
        }

        duration_ms = int((time.time() - start) * 1000)
        self._log_audit(
            state,
            action="external_discovery_completed",
            input_summary=(
                f"query: {state['raw_query'][:60]} | "
                f"constraints: {list(constraints.keys())}"
            ),
            output_summary=(
                f"web={len(web_results)}, stage1_pass={stage1_passed}, "
                f"extracted={len(extracted)}, validated={len(validated)}, "
                f"ingested={len(newly_added_ids)}, "
                f"rejected_sanctions={rejected_sanctions}, pending_sanctions={pending_sanctions}, "
                f"duplicates={rejected_duplicate}, missing_location={rejected_missing_location}"
            ),
            duration_ms=duration_ms,
            reasoning=(
                "Two-stage web extraction plus Geoapify location validation. "
                f"{len(newly_added_ids)} new suppliers added as pending review."
            ),
        )

        return state

    @staticmethod
    def _apply_verified_location(supplier: dict, location: VerifiedLocation) -> None:
        supplier["city"] = location.city
        supplier["country"] = location.country
        supplier["address"] = location.formatted_address or supplier.get("address")
        supplier["latitude"] = location.latitude
        supplier["longitude"] = location.longitude
        citations = supplier.setdefault("source_citations", {}) or {}
        citations["location"] = {
            "source": location.source,
            "confidence": location.confidence,
            "formatted_address": location.formatted_address,
        }
        supplier["source_citations"] = citations

    @staticmethod
    def _product_terms_from_constraints(constraints: dict) -> list[str]:
        terms: list[str] = []
        if constraints.get("product_type"):
            terms.append(str(constraints["product_type"]))
        terms.extend(str(term) for term in constraints.get("product_keywords") or [])

        cleaned_terms: list[str] = []
        seen: set[str] = set()
        for term in terms:
            cleaned = " ".join(term.strip().split())
            key = cleaned.casefold()
            if not cleaned or key in seen:
                continue
            seen.add(key)
            cleaned_terms.append(cleaned)
        return cleaned_terms[:8]

    def _is_duplicate(self, db, name: str, country: Optional[str]) -> bool:
        """Check if a supplier already exists by name + country (case-insensitive)."""
        from sqlalchemy import func, select

        query = select(Supplier).where(
            func.lower(Supplier.name) == name.lower(),
            Supplier.is_active == True,  # noqa: E712
        )
        if country:
            query = query.where(Supplier.country == country)

        result = db.execute(query)
        return result.scalars().first() is not None

    def _ingest_suppliers(self, suppliers: list[dict]) -> list[str]:
        """Add new suppliers to PostgreSQL (as pending_review) and Milvus."""
        if not suppliers:
            return []

        new_ids: list[str] = []
        try:
            with SyncSessionLocal() as db:
                supplier_objects = []
                for s in suppliers:
                    supplier_id = uuid.uuid4()
                    supplier = Supplier(
                        id=supplier_id,
                        name=s["name"],
                        description=s.get("description"),
                        category=s.get("category"),
                        country=s.get("country"),
                        city=s.get("city"),
                        address=s.get("address"),
                        latitude=s.get("latitude"),
                        longitude=s.get("longitude"),
                        certifications=s.get("certifications") or [],
                        certification_details=self._certification_details_from_citations(s),
                        capacity_value=s.get("capacity_value"),
                        capacity_unit=s.get("capacity_unit"),
                        lead_time_days=s.get("lead_time_days"),
                        website=s.get("website"),
                        contact_email=s.get("contact_email"),
                        source="web_discovery",
                        # Web-discovered suppliers enter a pending-review state
                        # so they never bypass manager approval. They are still
                        # embedded after commit and shown with a badge in search.
                        status=SupplierStatus.pending_review,
                        source_url=s.get("source_url"),
                        source_citations=s.get("source_citations") or {},
                        is_active=True,
                    )
                    db.add(supplier)
                    supplier_objects.append((supplier_id, s))
                    new_ids.append(str(supplier_id))

                db.commit()

            vs = get_vector_store()
            embed_dicts = [
                {**s, "id": new_ids[i]}
                for i, (sid, s) in enumerate(supplier_objects)
            ]
            vs.add_suppliers(embed_dicts)

            logger.debug("[external_discovery] Ingested %d new suppliers", len(new_ids))

        except Exception as e:
            logger.error("[external_discovery] Ingestion failed: %s", e)

        return new_ids

    @staticmethod
    def _certification_details_from_citations(supplier: dict) -> dict:
        certifications = supplier.get("certifications") or []
        citations = supplier.get("source_citations") or {}
        cert_citation = citations.get("certifications") if isinstance(citations, dict) else None
        per_cert = {}
        if isinstance(cert_citation, dict):
            per_cert = cert_citation.get("certifications") or {}

        details = {}
        for cert in certifications:
            evidence = per_cert.get(cert) if isinstance(per_cert, dict) else None
            if isinstance(evidence, dict):
                details[cert] = {
                    "source_url": evidence.get("url"),
                    "source_phrase": evidence.get("source_phrase"),
                }
            elif isinstance(cert_citation, dict):
                details[cert] = {
                    "source_url": cert_citation.get("url"),
                    "source_phrase": cert_citation.get("source_phrase"),
                }
        return details
