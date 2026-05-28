"""
app/agents/external_discovery_agent.py — Discovers NEW suppliers from external sources.

PRODUCTION V2 CHANGES:
- Two-stage extraction (stage1_classify → stage2_extract)
- Source URL and citations stored per supplier
- Suppliers ingested as SupplierStatus.discovered (Tier 3)
- Richer description generation for better semantic search matching
"""

import logging
import time
import uuid
from typing import Optional

from app.agents.base import BaseAgent
from app.agents.state import AgentState
from app.core.config import settings
from app.db.session import SyncSessionLocal
from app.db.models import Supplier, SupplierStatus
from app.services.web_search import get_web_search_service
from app.services.wikidata import get_wikidata_service
from app.services.sanctions import get_sanctions_service
from app.services.supplier_extraction import SupplierExtractionService
from app.core.vector_store import get_vector_store
from app.core.embeddings import get_embedding_client

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
        self.wikidata = get_wikidata_service()
        self.sanctions = get_sanctions_service()
        self.extractor = SupplierExtractionService()

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
        web_results = self.web_search.search_suppliers(
            category=constraints.get("category_hint") or constraints.get("category"),
            country=self._extract_country_from_constraints(constraints),
            city=self._extract_city_from_constraints(constraints),
            certifications=constraints.get("certifications"),
            max_results=settings.EXTERNAL_DISCOVERY_MAX_RESULTS,
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

        with SyncSessionLocal() as db:
            for s in extracted:
                screening = self.sanctions.screen_company(s["name"])
                if screening.is_flagged:
                    logger.warning(
                        "[external_discovery] REJECTED (sanctions): %s — lists: %s",
                        s["name"], screening.matched_lists,
                    )
                    rejected_sanctions += 1
                    continue

                if self._is_duplicate(db, s["name"], s.get("country")):
                    logger.debug("[external_discovery] Duplicate: %r", s["name"])
                    rejected_duplicate += 1
                    continue

                wd_data = self.wikidata.lookup_company(s["name"])
                if wd_data:
                    s["wikidata_id"] = wd_data.get("wikidata_id")
                    if not s.get("country") and wd_data.get("country"):
                        s["country"] = wd_data["country"]

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
            "rejected_duplicates": rejected_duplicate,
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
                f"rejected_sanctions={rejected_sanctions}, duplicates={rejected_duplicate}"
            ),
            duration_ms=duration_ms,
            reasoning=(
                f"Two-stage web extraction. "
                f"{len(newly_added_ids)} new suppliers added as discovered (Tier 3)."
            ),
        )

        return state

    def _is_duplicate(self, db, name: str, country: Optional[str]) -> bool:
        """Check if a supplier already exists by name + country (case-insensitive)."""
        from sqlalchemy import select, func
        query = select(Supplier).where(
            func.lower(Supplier.name) == name.lower(),
            Supplier.is_active == True,  # noqa: E712
        )
        if country:
            query = query.where(Supplier.country == country)

        result = db.execute(query)
        return result.scalars().first() is not None

    def _ingest_suppliers(self, suppliers: list[dict]) -> list[str]:
        """Add new suppliers to PostgreSQL (as discovered) and Milvus."""
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
                        latitude=s.get("latitude"),
                        longitude=s.get("longitude"),
                        certifications=s.get("certifications") or [],
                        certification_details={},
                        capacity_value=s.get("capacity_value"),
                        capacity_unit=s.get("capacity_unit"),
                        lead_time_days=s.get("lead_time_days"),
                        website=s.get("website"),
                        contact_email=s.get("contact_email"),
                        source="web_discovery",
                        # Production v2: new fields
                        status=SupplierStatus.discovered,
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

