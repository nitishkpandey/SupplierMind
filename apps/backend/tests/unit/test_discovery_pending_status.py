"""
Sprint A — Human-in-the-loop discovery (pending_review holding state).

These tests pin the core invariant of the HITL change: web-discovered
suppliers must land in the database as status=pending_review (a holding
state awaiting admin approval) instead of status=discovered, so they no
longer silently bypass the approval workflow — while STILL being embedded
so they remain searchable.

Following the house style (see test_rbac.py), we mock the persistence and
vector-store dependencies rather than spinning up a real DB: the goal is to
pin the ingestion *decision*, not exercise Postgres/Milvus.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.agents.discovery_agent import DiscoveryAgent
from app.agents.external_discovery_agent import ExternalDiscoveryAgent
from app.agents.ranking_agent import RankingAgent
from app.db.models import Supplier, SupplierStatus
from app.db.session import AsyncSessionLocal, SyncSessionLocal, async_engine
from app.evaluation.baselines import keyword_baseline_search, manual_baseline_search
from app.evaluation.runner import (
    _fetch_supplier_dicts,
    _load_supplier_name_index,
    _normalise_name,
)


def _ingest_one(supplier_dict: dict):
    """
    Run ExternalDiscoveryAgent._ingest_suppliers against mocked
    SyncSessionLocal + vector store, returning the captured Supplier ORM
    objects, the returned ids, and the mocked vector store.

    _ingest_suppliers reads no instance state, so we bypass __init__
    (which would construct live web/sanctions/location services) via
    __new__.
    """
    captured: list = []

    fake_db = MagicMock()
    fake_db.add.side_effect = captured.append
    fake_db.commit = MagicMock()

    fake_session_cm = MagicMock()
    fake_session_cm.__enter__.return_value = fake_db
    fake_session_cm.__exit__.return_value = False

    fake_vs = MagicMock()

    with patch(
        "app.agents.external_discovery_agent.SyncSessionLocal",
        return_value=fake_session_cm,
    ), patch(
        "app.agents.external_discovery_agent.get_vector_store",
        return_value=fake_vs,
    ):
        agent = ExternalDiscoveryAgent.__new__(ExternalDiscoveryAgent)
        new_ids = agent._ingest_suppliers([supplier_dict])

    return captured, new_ids, fake_vs


def test_web_discovered_supplier_persisted_as_pending_review():
    """A web-discovered supplier is added with status=pending_review, NOT
    discovered — so it enters the admin-approval holding state."""
    captured, new_ids, _ = _ingest_one(
        {
            "name": "Acme Forge GmbH",
            "description": "Precision steel forging for aerospace.",
            "category": "metals",
            "address": "Hauptstrasse 1, Bremen, Germany",
            "country": "Germany",
            "city": "Bremen",
            "certifications": ["ISO 9001"],
        }
    )

    assert len(captured) == 1, "exactly one supplier should be persisted"
    supplier = captured[0]

    assert supplier.status == SupplierStatus.pending_review, (
        f"web-discovered supplier must enter as pending_review, "
        f"got {supplier.status!r}"
    )
    assert supplier.status != SupplierStatus.discovered, (
        "regression guard: discovery must no longer bypass approval via "
        "status=discovered"
    )
    assert supplier.source == "web_discovery"
    assert supplier.address == "Hauptstrasse 1, Bremen, Germany"
    assert supplier.city == "Bremen"
    assert supplier.country == "Germany"
    assert len(new_ids) == 1


def test_pending_supplier_still_gets_embedded():
    """Even though it's held for review, the supplier is still embedded so
    it remains retrievable in normal search. In this discovery path the
    supplier's own id IS the vector id (its 'embedding_id'), so we assert it
    was indexed in the vector store under that id."""
    captured, new_ids, fake_vs = _ingest_one(
        {
            "name": "Bremen Alloys Ltd",
            "description": "Aluminium alloy supplier.",
            "country": "Germany",
        }
    )

    fake_vs.add_suppliers.assert_called_once()
    embed_dicts = fake_vs.add_suppliers.call_args[0][0]
    assert len(embed_dicts) == 1
    assert embed_dicts[0]["id"] == new_ids[0], (
        "pending supplier must still be embedded (indexed under its id) — "
        "the holding state must not skip embedding"
    )


def test_external_discovery_rejects_supplier_without_verified_location():
    """Web suppliers must not be ingested unless location enrichment verifies
    city/country/coordinates. This prevents Pending Review from filling with
    unusable 'Location not verified' supplier cards."""
    web_result = SimpleNamespace(
        title="Hogge Precision",
        url="https://hogge.example",
        snippet="AS9100D aerospace machining supplier.",
    )
    agent = ExternalDiscoveryAgent.__new__(ExternalDiscoveryAgent)
    agent.web_search = SimpleNamespace(
        is_available=True,
        search_suppliers=MagicMock(return_value=[web_result]),
    )
    agent.extractor = SimpleNamespace(
        stage1_classify=MagicMock(return_value={"is_supplier": True, "confidence": 0.95}),
        stage2_extract=MagicMock(return_value={
            "name": "Hogge Precision",
            "description": "AS9100D aerospace machining supplier.",
            "country": None,
            "city": None,
            "address": None,
            "certifications": ["AS9100D"],
            "source_citations": {},
        }),
    )
    agent.location_enricher = SimpleNamespace(enrich=MagicMock(return_value=None))
    agent.sanctions = SimpleNamespace()
    agent._log_audit = MagicMock()
    agent._ingest_suppliers = MagicMock()

    state = {
        "raw_query": "AS9100 certified aerospace machining suppliers in Bavaria",
        "parsed_constraints": {
            "certifications": ["AS9100"],
            "location_city": "Bavaria",
            "location_country": "Germany",
        },
        "audit_log": [],
    }

    result = agent.execute(state)

    agent._ingest_suppliers.assert_not_called()
    assert result["newly_discovered_supplier_ids"] == []
    assert result["external_discovery_stats"]["rejected_missing_location"] == 1


# ─────────────────────────────────────────────────────────────────────
# Commit 3 — search includes pending (UI), benchmark excludes it.
#
# These tests touch the real DB but ALWAYS roll back, so the frozen
# SupplierBench-25 corpus is never mutated. They compare a pending_review
# supplier against an approved one sharing a unique keyword, which proves
# the status filter (not mere non-matching) is what excludes pending.
# ─────────────────────────────────────────────────────────────────────

_KW = "zzqforgetoken"  # nonsense token guaranteed absent from the corpus


def test_pending_in_search_scope_but_excluded_on_eval_path():
    """Discovery scope can retrieve pending_review in the normal UI flow,
    while approved_only and eval paths filter it out."""
    agent = DiscoveryAgent.__new__(DiscoveryAgent)  # _filter_ids_by_scope is stateless
    with SyncSessionLocal() as db:
        pending = Supplier(
            name="ZzqscopePending GmbH",
            description=f"{_KW} pending scope test",
            status=SupplierStatus.pending_review,
            is_active=True,
        )
        db.add(pending)
        db.flush()
        pid = str(pending.id)

        approved_only = agent._filter_ids_by_scope(
            db, [pid], "approved_only", "", exclude_pending=False
        )
        assert pid not in approved_only, "approved_only must not include pending suppliers"

        included = agent._filter_ids_by_scope(
            db, [pid], "both", "", exclude_pending=False
        )
        assert pid in included, "pending must show in discover-new-suppliers scope"

        excluded = agent._filter_ids_by_scope(
            db, [pid], "both", "", exclude_pending=True
        )
        assert pid not in excluded, (
            "eval path must exclude pending even in discovery scope"
        )

        db.rollback()


def test_scope_filter_excludes_inactive_suppliers():
    """Soft-deleted rows must not re-enter results through stale vector hits."""
    agent = DiscoveryAgent.__new__(DiscoveryAgent)

    with SyncSessionLocal() as db:
        inactive = Supplier(
            name="ZzqInactive Pending GmbH",
            description="Stale vector-hit fixture",
            status=SupplierStatus.pending_review,
            is_active=False,
        )
        db.add(inactive)
        db.flush()
        sid = str(inactive.id)

        included = agent._filter_ids_by_scope(
            db, [sid], "both", "", exclude_pending=False
        )

        assert sid not in included
        db.rollback()


def test_newly_discovered_ids_are_carried_into_current_candidate_set():
    """A fresh web-discovered supplier must survive the handoff into internal
    discovery even when vector/SQL retrieval would otherwise return only older
    database rows. This is the UI bug path for "Discover New Suppliers":
    external_discovery ingests the supplier, but the current query's shortlist
    must not depend on rediscovering that row from the index immediately."""
    agent = DiscoveryAgent.__new__(DiscoveryAgent)

    with SyncSessionLocal() as db:
        existing = Supplier(
            name="ZzqExisting Electronics GmbH",
            description=f"{_KW} existing approved match",
            category="zzq_scope_unique",
            status=SupplierStatus.approved,
            is_active=True,
        )
        fresh = Supplier(
            name="ZzqFresh Web Candidate GmbH",
            description=f"{_KW} fresh web candidate",
            category="specialty",
            status=SupplierStatus.pending_review,
            source="web_discovery",
            is_active=True,
        )
        db.add_all([existing, fresh])
        db.flush()
        existing_id = str(existing.id)
        fresh_id = str(fresh.id)

        fake_vs = MagicMock()
        fake_vs.search.return_value = [
            SimpleNamespace(supplier_id=existing_id, similarity_score=0.91)
        ]
        fake_session_cm = MagicMock()
        fake_session_cm.__enter__.return_value = db
        fake_session_cm.__exit__.return_value = False

        state = {
            "raw_query": "find fresh electronics supplier",
            "parsed_constraints": {"category_hint": "zzq_scope_unique"},
            "newly_discovered_supplier_ids": [fresh_id],
            "candidate_supplier_ids": [],
            "semantic_scores": {},
            "geo_distances": {},
            "relaxed_constraints": [],
            "tier_assignments": {},
            "retry_count": 3,
            "search_scope": "both",
            "user_id": "",
            "exclude_pending": False,
            "audit_log": [],
        }

        with patch("app.core.vector_store.get_vector_store", return_value=fake_vs), patch(
            "app.agents.discovery_agent.SyncSessionLocal",
            return_value=fake_session_cm,
        ):
            result = agent.execute(state)

        assert existing_id in result["candidate_supplier_ids"]
        assert fresh_id in result["candidate_supplier_ids"], (
            "freshly ingested web supplier IDs must be injected into the "
            "current query's candidate set; otherwise Discover New Suppliers "
            "can return only pre-existing database suppliers"
        )
        assert result["tier_assignments"][fresh_id] == "pending_review"

        db.rollback()


def test_structured_keyword_search_uses_postgres_corpus_when_vector_index_misses():
    """Product keywords should retrieve active DB suppliers even when semantic
    search returns nothing. This keeps the loaded 10k Postgres corpus useful
    while the Milvus index is catching up."""
    agent = DiscoveryAgent.__new__(DiscoveryAgent)
    unique_kw = "zzqbronzegear"

    with SyncSessionLocal() as db:
        supplier = Supplier(
            name="Zzq Bronze Gear GmbH",
            description=f"Specialist manufacturer for {unique_kw} components.",
            category="metals",
            status=SupplierStatus.approved,
            is_active=True,
        )
        db.add(supplier)
        db.flush()
        supplier_id = str(supplier.id)

        fake_vs = MagicMock()
        fake_vs.search.return_value = []
        fake_session_cm = MagicMock()
        fake_session_cm.__enter__.return_value = db
        fake_session_cm.__exit__.return_value = False

        state = {
            "raw_query": f"Find {unique_kw} suppliers",
            "parsed_constraints": {
                "product_type": unique_kw,
                "product_keywords": [unique_kw],
            },
            "newly_discovered_supplier_ids": [],
            "candidate_supplier_ids": [],
            "semantic_scores": {},
            "geo_distances": {},
            "relaxed_constraints": [],
            "tier_assignments": {},
            "retry_count": 3,
            "search_scope": "approved_only",
            "user_id": "",
            "exclude_pending": False,
            "audit_log": [],
        }

        with patch("app.core.vector_store.get_vector_store", return_value=fake_vs), patch(
            "app.agents.discovery_agent.SyncSessionLocal",
            return_value=fake_session_cm,
        ):
            result = agent.execute(state)

        assert supplier_id in result["candidate_supplier_ids"]
        assert result["tier_assignments"][supplier_id] == "approved"

        db.rollback()


def test_qualified_fresh_pending_review_candidate_surfaces_in_query_results(monkeypatch):
    """A qualified fresh web supplier should still reach the current result list.

    Fresh web candidates enter the DB as pending_review so managers can approve
    or reject them. They must also be visible in the query results that created
    them when they clear the same credibility threshold as other candidates;
    otherwise the user only sees a growing Pending Review count.
    """
    agent = RankingAgent.__new__(RankingAgent)

    fresh_id = "fresh-web-candidate"
    approved_id = "approved-incumbent"

    monkeypatch.setattr(
        agent,
        "_fetch_suppliers",
        lambda supplier_ids: [
            {
                "id": approved_id,
                "name": "Approved Incumbent GmbH",
                "description": "Established approved supplier.",
                "category": "metals",
                "country": "Germany",
                "city": "Munich",
                "certifications": ["ISO 9001"],
                "capacity_value": 1000,
                "capacity_unit": "units/month",
                "lead_time_days": 30,
                "website": "https://approved.example",
                "contact_email": "sales@approved.example",
            },
            {
                "id": fresh_id,
                "name": "Fresh Web Candidate GmbH",
                "description": "Sparse but relevant web-discovered supplier.",
                "category": "metals",
                "country": "Germany",
                "city": "Bremen",
                "certifications": ["ISO 9001"],
                "capacity_value": 500,
                "capacity_unit": None,
                "lead_time_days": None,
                "website": "https://fresh.example",
                "contact_email": None,
            },
        ],
    )

    state = {
        "parsed_constraints": {"query_type": "general"},
        "compliance_results": [
            {
                "supplier_id": approved_id,
                "overall_pass": True,
                "pass_rate": 1.0,
                "compliance_results": [
                    {"constraint_name": "category", "status": "PASS", "reason": "Category matches"}
                ],
            },
            {
                "supplier_id": fresh_id,
                "overall_pass": True,
                "pass_rate": 0.75,
                "compliance_results": [
                    {
                        "constraint_name": "category",
                        "status": "PASS",
                        "reason": "Category matches",
                    }
                ],
            },
        ],
        "semantic_scores": {approved_id: 0.95, fresh_id: 0.65},
        "geo_distances": {},
        "tier_assignments": {
            approved_id: "approved",
            fresh_id: "pending_review",
        },
        "newly_discovered_supplier_ids": [fresh_id],
        "exclude_pending": False,
        "audit_log": [],
    }

    result = agent.execute(state)

    ranked_ids = [r["supplier_id"] for r in result["ranked_suppliers"]]
    assert fresh_id in ranked_ids, (
        "fresh web-discovered suppliers must appear in the originating query's "
        "results so managers can approve or reject from that context"
    )
    assert next(r for r in result["ranked_suppliers"] if r["supplier_id"] == fresh_id)["tier"] == "pending_review"


@pytest.mark.asyncio
async def test_pending_excluded_from_baselines():
    """Both benchmark baselines (keyword + manual) must skip pending_review
    suppliers while still returning the approved one that shares the keyword."""
    # This is the only place in the suite that opens a real async session.
    # pytest-asyncio (auto mode) gives each test its own event loop, so we
    # dispose the pooled async engine afterwards to avoid leaving a connection
    # bound to a now-dead loop ("Event loop is closed") for the next test.
    try:
        async with AsyncSessionLocal() as db:
            approved = Supplier(
                name="Zzqforge Approved GmbH",
                description=f"{_KW} precision metal parts",
                status=SupplierStatus.approved,
                is_active=True,
            )
            pending = Supplier(
                name="Zzqforge Pending GmbH",
                description=f"{_KW} precision metal parts",
                status=SupplierStatus.pending_review,
                is_active=True,
            )
            db.add_all([approved, pending])
            await db.flush()
            aid, pid = str(approved.id), str(pending.id)

            kw, _ = await keyword_baseline_search(_KW, db, top_k=20)
            kw_ids = [s["id"] for s in kw]
            assert aid in kw_ids, "approved supplier should match the keyword baseline"
            assert pid not in kw_ids, "pending must be excluded from keyword baseline"

            mn, _ = await manual_baseline_search(_KW, db, top_k=20)
            mn_ids = [s["id"] for s in mn]
            assert aid in mn_ids, "approved supplier should match the manual baseline"
            assert pid not in mn_ids, "pending must be excluded from manual baseline"

            await db.rollback()
    finally:
        await async_engine.dispose()


@pytest.mark.asyncio
async def test_pending_excluded_from_eval_corpus():
    """The P1 name index and P2 corpus fetch must omit pending_review rows so
    the parametric / RAG baselines can never be scored against held suppliers."""
    try:
        async with AsyncSessionLocal() as db:
            approved = Supplier(
                name="ZzqcorpApproved GmbH",
                description=f"{_KW} corpus test",
                status=SupplierStatus.approved,
                is_active=True,
            )
            pending = Supplier(
                name="ZzqcorpPending GmbH",
                description=f"{_KW} corpus test",
                status=SupplierStatus.pending_review,
                is_active=True,
            )
            db.add_all([approved, pending])
            await db.flush()
            aid, pid = str(approved.id), str(pending.id)

            # P2 corpus fetch
            dicts = await _fetch_supplier_dicts([aid, pid], db)
            fetched_ids = [d["id"] for d in dicts]
            assert aid in fetched_ids, "approved supplier belongs in the P2 corpus"
            assert pid not in fetched_ids, "pending must be excluded from the P2 corpus"

            # P1 name index
            name_index = await _load_supplier_name_index(db)
            assert _normalise_name("ZzqcorpApproved GmbH") in name_index
            assert _normalise_name("ZzqcorpPending GmbH") not in name_index, (
                "pending name must not enter the P1 matching index"
            )

            await db.rollback()
    finally:
        await async_engine.dispose()


@pytest.mark.asyncio
async def test_eval_entrypoint_threads_exclude_pending_true():
    """The critical reproducibility guard: run_suppliermind_query must call the
    pipeline with exclude_pending=True so a pending supplier in the DB can never
    reach SupplierMind eval scoring — independent of search scope."""
    from app.evaluation import runner

    captured = {}

    async def fake_run_pipeline(raw_query, query_id, *, user_id, exclude_pending=False, **kw):
        captured["exclude_pending"] = exclude_pending
        return {"ranked_suppliers": [], "compliance_results": []}

    with patch("app.agents.orchestrator.run_pipeline", fake_run_pipeline):
        await runner.run_suppliermind_query("any query", {}, "eval-test")

    assert captured.get("exclude_pending") is True, (
        "eval path must pass exclude_pending=True into the pipeline"
    )
