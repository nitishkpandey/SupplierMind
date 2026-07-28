import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Supplier, SupplierStatus

DEMO_FIXTURE = (
    Path(__file__).resolve().parents[2] / "demo" / "german_breweries.json"
)


class _VectorStore:
    def __init__(self) -> None:
        self.supplier_ids: set[str] = set()

    def delete_supplier(self, supplier_id: str) -> None:
        self.supplier_ids.discard(supplier_id)

    def add_suppliers(self, suppliers: list[dict]) -> list[str]:
        ids = [str(supplier["id"]) for supplier in suppliers]
        self.supplier_ids.update(ids)
        return ids


def _demo_seed_api():
    from app.services.demo_seed import (
        load_demo_records,
        seed_demo_suppliers,
        stable_demo_supplier_id,
    )

    return load_demo_records, seed_demo_suppliers, stable_demo_supplier_id


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Supplier.__table__.create(engine)
    return Session(engine)


def test_demo_fixture_is_separate_source_cited_and_approved():
    load_demo_records, _, _ = _demo_seed_api()

    records = load_demo_records(DEMO_FIXTURE)

    assert 4 <= len(records) <= 6
    for record in records:
        assert record["source"] == "demo_manual"
        assert record["status"] == "approved"
        assert record["source_url"].startswith("https://")
        assert record["source_citations"]["products"]["url"].startswith("https://")
        assert record["source_citations"]["location"]["url"].startswith("https://")
        assert record["country"] == "Germany"
        assert record["latitude"] is not None
        assert record["longitude"] is not None
        assert record["capacity_value"] is None
        assert record["lead_time_days"] is None


def test_demo_supplier_ids_are_stable():
    _, _, stable_demo_supplier_id = _demo_seed_api()

    first = stable_demo_supplier_id("paulaner-munich")
    second = stable_demo_supplier_id("paulaner-munich")
    different = stable_demo_supplier_id("hofbraeu-munich")

    assert first == second
    assert first != different


def test_demo_seed_is_idempotent_in_database_and_vector_store():
    load_demo_records, seed_demo_suppliers, _ = _demo_seed_api()
    records = load_demo_records(DEMO_FIXTURE)
    vector_store = _VectorStore()

    with _session() as db:
        first = seed_demo_suppliers(db, vector_store, records)
        second = seed_demo_suppliers(db, vector_store, records)
        suppliers = db.query(Supplier).order_by(Supplier.name).all()

    assert first.inserted == len(records)
    assert first.updated == 0
    assert first.indexed == len(records)
    assert second.inserted == 0
    assert second.updated == len(records)
    assert second.indexed == len(records)
    assert len(suppliers) == len(records)
    assert len(vector_store.supplier_ids) == len(records)
    assert all(supplier.source == "demo_manual" for supplier in suppliers)
    assert all(supplier.status == SupplierStatus.approved for supplier in suppliers)
    assert all(supplier.embedding_id == str(supplier.id) for supplier in suppliers)


def test_demo_seed_refuses_to_overwrite_non_demo_supplier():
    _, seed_demo_suppliers, stable_demo_supplier_id = _demo_seed_api()
    record = {
        "seed_key": "protected",
        "name": "Protected Supplier",
        "description": "A source-cited supplier.",
        "category": "food_ingredients",
        "country": "Germany",
        "city": "Munich",
        "address": "Example 1, 80331 Munich, Germany",
        "latitude": 48.13,
        "longitude": 11.57,
        "certifications": [],
        "capacity_value": None,
        "capacity_unit": None,
        "lead_time_days": None,
        "website": "https://protected.example",
        "contact_email": None,
        "source": "demo_manual",
        "status": "approved",
        "source_url": "https://protected.example/products",
        "source_citations": {
            "products": {
                "url": "https://protected.example/products",
                "source_phrase": "A source-cited supplier.",
            },
            "location": {
                "url": "https://protected.example/imprint",
                "source_phrase": "Example 1, 80331 Munich, Germany",
            },
        },
    }
    supplier_id = stable_demo_supplier_id("protected")

    with _session() as db:
        db.add(Supplier(
            id=supplier_id,
            name="Existing Manual Supplier",
            source="manual",
            status=SupplierStatus.approved,
            is_active=True,
        ))
        db.commit()

        with pytest.raises(ValueError, match="non-demo supplier"):
            seed_demo_suppliers(db, _VectorStore(), [record])

        existing = db.get(Supplier, supplier_id)

    assert existing is not None
    assert existing.name == "Existing Manual Supplier"


def test_demo_fixture_is_valid_json_before_service_validation():
    raw = json.loads(DEMO_FIXTURE.read_text(encoding="utf-8"))

    assert isinstance(raw, list)
    assert raw
