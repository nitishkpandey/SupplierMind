"""Idempotent ingestion for explicit, source-cited demo suppliers."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.vector_store import BaseVectorStore
from app.db.models import Supplier, SupplierStatus
from app.utils.text_normalization import clean_optional_text

DEMO_SOURCE = "demo_manual"
DEMO_NAMESPACE = uuid.UUID("0f6284b9-a391-4380-a1b2-4614354bcf49")
DEMO_APPROVAL_JUSTIFICATION = (
    "Approved source-cited supplier used as a deterministic production demo fallback."
)


@dataclass(frozen=True)
class DemoSeedStats:
    inserted: int
    updated: int
    indexed: int


def stable_demo_supplier_id(seed_key: str) -> uuid.UUID:
    cleaned_key = clean_optional_text(seed_key)
    if not cleaned_key:
        raise ValueError("Demo supplier seed_key is required")
    return uuid.uuid5(DEMO_NAMESPACE, cleaned_key.casefold())


def load_demo_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("Demo supplier fixture must be a non-empty JSON list")

    records: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for raw in payload:
        if not isinstance(raw, dict):
            raise ValueError("Every demo supplier record must be a JSON object")
        record = dict(raw)
        _validate_demo_record(record)
        seed_key = str(record["seed_key"]).casefold()
        if seed_key in seen_keys:
            raise ValueError(f"Duplicate demo supplier seed_key: {record['seed_key']}")
        seen_keys.add(seed_key)
        records.append(record)
    return records


def seed_demo_suppliers(
    db: Session,
    vector_store: BaseVectorStore,
    records: list[dict[str, Any]],
) -> DemoSeedStats:
    for record in records:
        _validate_demo_record(record)

    inserted = 0
    updated = 0
    suppliers: list[Supplier] = []
    vector_payloads: list[dict[str, Any]] = []
    decided_at = datetime.now(UTC)

    try:
        for record in records:
            supplier_id = stable_demo_supplier_id(str(record["seed_key"]))
            supplier = db.get(Supplier, supplier_id)
            if supplier is not None and supplier.source != DEMO_SOURCE:
                raise ValueError(
                    f"Refusing to overwrite non-demo supplier at stable ID {supplier_id}"
                )

            values = _supplier_values(record, decided_at=decided_at)
            if supplier is None:
                supplier = Supplier(id=supplier_id, **values)
                db.add(supplier)
                inserted += 1
            else:
                for field, value in values.items():
                    setattr(supplier, field, value)
                updated += 1

            suppliers.append(supplier)
            vector_payloads.append({
                **record,
                "id": str(supplier_id),
            })

        db.flush()

        for supplier in suppliers:
            vector_store.delete_supplier(str(supplier.id))
        embedding_ids = vector_store.add_suppliers(vector_payloads)
        if len(embedding_ids) != len(suppliers):
            raise RuntimeError(
                "Vector store returned a different number of demo embedding IDs"
            )

        for supplier, embedding_id in zip(
            suppliers,
            embedding_ids,
            strict=True,
        ):
            supplier.embedding_id = str(embedding_id)

        db.commit()
    except Exception:
        db.rollback()
        raise

    return DemoSeedStats(
        inserted=inserted,
        updated=updated,
        indexed=len(suppliers),
    )


def _validate_demo_record(record: dict[str, Any]) -> None:
    required_text = (
        "seed_key",
        "name",
        "description",
        "category",
        "country",
        "city",
        "address",
        "website",
        "source_url",
    )
    for field in required_text:
        if not clean_optional_text(record.get(field)):
            raise ValueError(f"Demo supplier {field} is required")

    if record.get("source") != DEMO_SOURCE:
        raise ValueError(f"Demo supplier source must be {DEMO_SOURCE!r}")
    if record.get("status") != SupplierStatus.approved.value:
        raise ValueError("Demo supplier status must be 'approved'")
    if record.get("country") != "Germany":
        raise ValueError("The German brewery demo fixture must use country='Germany'")
    if record.get("capacity_value") is not None:
        raise ValueError("Demo capacity must remain null unless independently sourced")
    if record.get("capacity_unit") is not None:
        raise ValueError("Demo capacity_unit must remain null with null capacity")
    if record.get("lead_time_days") is not None:
        raise ValueError("Demo lead time must remain null unless independently sourced")

    latitude = record.get("latitude")
    longitude = record.get("longitude")
    if not isinstance(latitude, int | float) or not -90 <= latitude <= 90:
        raise ValueError("Demo supplier latitude must be numeric and valid")
    if not isinstance(longitude, int | float) or not -180 <= longitude <= 180:
        raise ValueError("Demo supplier longitude must be numeric and valid")

    citations = record.get("source_citations")
    if not isinstance(citations, dict):
        raise ValueError("Demo supplier source_citations must be an object")
    for field in ("products", "location"):
        citation = citations.get(field)
        if not isinstance(citation, dict):
            raise ValueError(f"Demo supplier {field} citation is required")
        url = clean_optional_text(citation.get("url"))
        phrase = clean_optional_text(citation.get("source_phrase"))
        if not url or not url.startswith("https://") or not phrase:
            raise ValueError(
                f"Demo supplier {field} citation needs an HTTPS URL and source phrase"
            )


def _supplier_values(
    record: dict[str, Any],
    *,
    decided_at: datetime,
) -> dict[str, Any]:
    return {
        "name": record["name"],
        "description": record["description"],
        "category": record["category"],
        "country": record["country"],
        "city": record["city"],
        "address": record["address"],
        "latitude": float(record["latitude"]),
        "longitude": float(record["longitude"]),
        "certifications": list(record.get("certifications") or []),
        "certification_details": {},
        "capacity_value": record.get("capacity_value"),
        "capacity_unit": record.get("capacity_unit"),
        "lead_time_days": record.get("lead_time_days"),
        "website": record["website"],
        "contact_email": record.get("contact_email"),
        "source": DEMO_SOURCE,
        "status": SupplierStatus.approved,
        "source_url": record["source_url"],
        "source_citations": dict(record["source_citations"]),
        "approved_at": decided_at,
        "approval_justification": DEMO_APPROVAL_JUSTIFICATION,
        "approval_action": SupplierStatus.approved.value,
        "approval_decided_at": decided_at,
        "is_active": True,
    }
