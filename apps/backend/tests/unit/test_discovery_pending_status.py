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

from unittest.mock import MagicMock, patch

import pytest

from app.agents.discovery_agent import DiscoveryAgent
from app.agents.external_discovery_agent import ExternalDiscoveryAgent
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
    (which would construct live web/wikidata/sanctions services) via
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
            "country": "Germany",
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
    """Discovery scope: pending_review is retrieved in the normal (UI) flow,
    but the eval path (exclude_pending=True) filters it out — proving the UI
    and benchmark diverge by design, not by scope alone."""
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

        included = agent._filter_ids_by_scope(
            db, [pid], "approved_only", "", exclude_pending=False
        )
        assert pid in included, "pending must show in the normal (UI) search scope"

        excluded = agent._filter_ids_by_scope(
            db, [pid], "approved_only", "", exclude_pending=True
        )
        assert pid not in excluded, (
            "eval path must exclude pending even in approved_only scope"
        )

        db.rollback()


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
