"""
app/services/ingestion.py — Supplier data ingestion service.

Loads suppliers from JSON → PostgreSQL (structured data) + Milvus (embeddings).

WHY TWO STORES?
PostgreSQL stores everything: name, certifications, capacity, lat/lng.
Milvus stores ONLY embeddings: 512 floats per supplier.

When searching:
1. Milvus finds semantically similar suppliers (returns IDs)
2. PostgreSQL fetches full details for those IDs

They must stay in sync:
- When a supplier is added → PostgreSQL first, then Milvus
- When a supplier is updated → update PostgreSQL, re-embed, update Milvus
- When a supplier is deleted → soft-delete in PostgreSQL, delete from Milvus
"""
import time
import json
import logging
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import get_embedding_client
from app.core.vector_store import get_vector_store
from app.db.models import Supplier
from app.db.repositories.supplier_repo import SupplierRepository

logger = logging.getLogger(__name__)


async def ingest_suppliers_from_json(
    db: AsyncSession,
    json_path: Path,
    batch_size: int = 20,
) -> dict:
    """
    Load suppliers from JSON file into PostgreSQL and Milvus.

    Args:
        db: Database session
        json_path: Path to suppliers_synthetic.json
        batch_size: How many suppliers to embed at once (Voyage AI batch limit)

    Returns:
        Summary dict with counts of inserted/skipped/failed
    """
    if not json_path.exists():
        raise FileNotFoundError(f"Dataset not found: {json_path}")

    with open(json_path, encoding="utf-8") as f:
        supplier_data = json.load(f)

    logger.info("Starting ingestion of %d suppliers from %s", len(supplier_data), json_path)

    supplier_repo = SupplierRepository(db)
    vector_store = get_vector_store()
    embed_client = get_embedding_client()

    stats = {"inserted": 0, "skipped": 0, "failed": 0}

    # Process in batches for efficient embedding
    for batch_start in range(0, len(supplier_data), batch_size):
        batch = supplier_data[batch_start : batch_start + batch_size]
        batch_to_insert = []

        for raw in batch:
            try:
                # Check for duplicates by original ID
                supplier_id = uuid.UUID(raw["id"])
                existing = await supplier_repo.get_by_id(supplier_id)
                if existing is not None:
                    logger.debug("Skipping existing supplier: %s", raw["name"])
                    stats["skipped"] += 1
                    continue

                batch_to_insert.append(raw)

            except Exception as e:
                logger.error("Failed to process supplier %s: %s", raw.get("name"), e)
                stats["failed"] += 1

        if not batch_to_insert:
            continue

        # Step 1: Insert into PostgreSQL
        inserted_suppliers = []
        for raw in batch_to_insert:
            try:
                supplier = Supplier(
                    id=uuid.UUID(raw["id"]),
                    name=raw["name"],
                    description=raw.get("description"),
                    category=raw.get("category"),
                    country=raw.get("country"),
                    city=raw.get("city"),
                    address=raw.get("address"),
                    latitude=raw.get("latitude"),
                    longitude=raw.get("longitude"),
                    certifications=raw.get("certifications", []),
                    certification_details=raw.get("certification_details", {}),
                    capacity_value=raw.get("capacity_value"),
                    capacity_unit=raw.get("capacity_unit"),
                    lead_time_days=raw.get("lead_time_days"),
                    website=raw.get("website"),
                    contact_email=raw.get("contact_email"),
                    is_active=raw.get("is_active", True),
                )
                db.add(supplier)
                inserted_suppliers.append(supplier)
            except Exception as e:
                logger.error("DB insert failed for %s: %s", raw.get("name"), e)
                stats["failed"] += 1

        # Flush to get IDs without committing yet
        await db.flush()

        # Step 2: Generate embeddings and insert into Milvus
        try:
            embedding_ids = vector_store.add_suppliers(
                [raw for raw in batch_to_insert if uuid.UUID(raw["id"]) in
                 {s.id for s in inserted_suppliers}]
            )

            # Step 3: Update PostgreSQL with embedding IDs
            for supplier, emb_id in zip(inserted_suppliers, embedding_ids):
                supplier.embedding_id = emb_id

            await db.flush()
            stats["inserted"] += len(inserted_suppliers)

            logger.info(
                "Batch %d-%d: inserted %d suppliers",
                batch_start + 1,
                batch_start + len(batch),
                len(inserted_suppliers),
            )

        except Exception as e:
            logger.error("Milvus indexing failed for batch: %s", e)
            # Still count as inserted (PostgreSQL worked, Milvus can be re-indexed)
            stats["inserted"] += len(inserted_suppliers)

        # Wait 20 seconds between batches (3 RPM = 1 req per 20s)
        time.sleep(20)

    await db.commit()
    logger.info(
        "Ingestion complete. inserted=%d skipped=%d failed=%d",
        stats["inserted"], stats["skipped"], stats["failed"]
    )
    return stats
