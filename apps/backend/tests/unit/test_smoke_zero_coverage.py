"""Smoke tests for the three load-bearing modules that were at 0% coverage
(Audit E): app/core/cache.py, app/evaluation/report.py, app/services/ingestion.py.

Goal is breakage-detection before later refactors, not full coverage: one
happy-path each, all external services mocked, each well under 5s.
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

BACKEND = Path(__file__).resolve().parents[2]


# ── app/core/cache.py ────────────────────────────────────────────────
async def test_inmemory_cache_set_get_delete_roundtrip():
    """InMemoryCache.set/get/exists/delete round-trip (the main cache path)."""
    from app.core.cache import InMemoryCache

    cache = InMemoryCache()
    await cache.set("smoke_key", {"v": 1}, ttl=60)

    assert await cache.exists("smoke_key") is True
    assert await cache.get("smoke_key") == {"v": 1}

    await cache.delete("smoke_key")
    assert await cache.get("smoke_key") is None
    assert await cache.exists("smoke_key") is False


# ── app/evaluation/report.py ─────────────────────────────────────────
def test_generate_thesis_report_smoke(tmp_path, monkeypatch):
    """generate_thesis_report builds a report dict from real results JSON.

    Uses the committed evaluation_results.json (schema-stable) as input and
    redirects the output file to tmp so the real thesis_report.json is not
    overwritten.
    """
    from app.evaluation import report

    results_path = BACKEND / "data" / "evaluation_results.json"
    monkeypatch.setattr(report, "REPORT_FILE", tmp_path / "thesis_report.json")

    out = report.generate_thesis_report(results_path)

    assert "metadata" in out
    assert "thesis_table" in out
    assert "rq2_performance_comparison" in out
    assert (tmp_path / "thesis_report.json").exists()


# ── app/services/ingestion.py ────────────────────────────────────────
async def test_ingest_suppliers_from_json_smoke(tmp_path, monkeypatch):
    """ingest_suppliers_from_json happy path: one supplier, all I/O mocked.

    Mocks the repository (no DB), vector store + embedding client (no Milvus/
    Voyage), and neutralises the 20s inter-batch rate-limit sleep.
    """
    import json

    from app.services import ingestion

    supplier = {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "Test Metals GmbH",
        "description": "smoke-test supplier",
        "category": "metals",
        "country": "Germany",
        "city": "Berlin",
        "certifications": ["ISO 9001"],
        "capacity_value": 1000,
        "capacity_unit": "units/month",
        "lead_time_days": 10,
    }
    json_path = tmp_path / "suppliers.json"
    json_path.write_text(json.dumps([supplier]), encoding="utf-8")

    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=None)  # supplier does not yet exist
    monkeypatch.setattr(ingestion, "SupplierRepository", lambda db: repo)

    vstore = MagicMock()
    vstore.add_suppliers = MagicMock(return_value=["emb-1"])
    monkeypatch.setattr(ingestion, "get_vector_store", lambda: vstore)
    monkeypatch.setattr(ingestion, "get_embedding_client", lambda: MagicMock())
    monkeypatch.setattr(ingestion.time, "sleep", lambda *_: None)  # no 20s wait

    db = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    stats = await ingestion.ingest_suppliers_from_json(db, json_path, batch_size=20)

    assert stats == {"inserted": 1, "skipped": 0, "failed": 0}
    vstore.add_suppliers.assert_called_once()
    db.commit.assert_awaited_once()
