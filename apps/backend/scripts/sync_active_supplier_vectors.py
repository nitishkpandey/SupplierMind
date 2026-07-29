"""Index active Postgres suppliers missing from the supplier vector collection.

Use this when `/api/v1/suppliers/stats` reports `out_of_sync`.

The synthetic bulk loader only covers the 10k generated corpus. This script is
the production repair path for approved manual suppliers and web-discovered
pending-review suppliers that are active in Postgres but missing from Milvus.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pymilvus import Collection, connections  # noqa: E402
from sqlalchemy import select, update  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.vector_store import COLLECTION_NAME, create_vector_store  # noqa: E402
from app.db.models import Supplier  # noqa: E402
from app.db.session import SyncSessionLocal  # noqa: E402
from app.platform.ai.context import (  # noqa: E402
    ai_request_scope,
    new_query_ai_context,
)
from app.platform.ai.types import DataClassification  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 40
DEFAULT_SLEEP_SECONDS = 60
MILVUS_QUERY_LIMIT = 16000


def _indexed_supplier_ids() -> set[str]:
    connections.connect(
        alias="default",
        host=settings.MILVUS_HOST,
        port=settings.MILVUS_PORT,
    )
    collection = Collection(COLLECTION_NAME)
    collection.load()
    rows = collection.query(
        expr='supplier_id != ""',
        output_fields=["supplier_id"],
        limit=MILVUS_QUERY_LIMIT,
    )
    if collection.num_entities >= MILVUS_QUERY_LIMIT:
        logger.warning(
            "Milvus collection has %d entities; query limit is %d. "
            "This script is safe for the current thesis/product dataset, but "
            "needs pagination before much larger production corpora.",
            collection.num_entities,
            MILVUS_QUERY_LIMIT,
        )
    return {str(row["supplier_id"]) for row in rows}


def _supplier_to_vector_dict(supplier: Supplier) -> dict:
    return {
        "id": str(supplier.id),
        "name": supplier.name,
        "description": supplier.description,
        "category": supplier.category,
        "country": supplier.country,
        "city": supplier.city,
        "certifications": supplier.certifications or [],
    }


def _missing_active_suppliers() -> list[Supplier]:
    indexed_ids = _indexed_supplier_ids()
    with SyncSessionLocal() as db:
        suppliers = db.execute(
            select(Supplier)
            .where(Supplier.is_active.is_(True))
            .order_by(Supplier.created_at.asc())
        ).scalars().all()
    return [supplier for supplier in suppliers if str(supplier.id) not in indexed_ids]


def sync_missing(batch_size: int, sleep_seconds: int, dry_run: bool) -> int:
    missing = _missing_active_suppliers()
    logger.info("Active suppliers missing vectors: %d", len(missing))
    if dry_run or not missing:
        for supplier in missing[:20]:
            logger.info("missing: %s | %s | %s", supplier.id, supplier.name, supplier.source)
        return len(missing)

    vector_store = create_vector_store()
    indexed_count = 0
    context = new_query_ai_context(
        purpose="supplier.indexing",
        classification=DataClassification.internal,
        user_id=None,
        query_id=None,
        correlation_id="sync-active-supplier-vectors",
    )
    for batch_start in range(0, len(missing), batch_size):
        batch = missing[batch_start : batch_start + batch_size]
        vector_payload = [_supplier_to_vector_dict(supplier) for supplier in batch]
        with ai_request_scope(context):
            indexed_ids = vector_store.add_suppliers(vector_payload)
        indexed_count += len(indexed_ids)

        with SyncSessionLocal() as db:
            for supplier, embedding_id in zip(batch, indexed_ids, strict=False):
                db.execute(
                    update(Supplier)
                    .where(Supplier.id == supplier.id)
                    .values(embedding_id=embedding_id)
                )
            db.commit()

        logger.info(
            "Indexed batch %d-%d (%d/%d)",
            batch_start + 1,
            batch_start + len(batch),
            indexed_count,
            len(missing),
        )
        if batch_start + len(batch) < len(missing):
            time.sleep(sleep_seconds)

    return indexed_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--sleep-seconds", type=int, default=DEFAULT_SLEEP_SECONDS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    count = sync_missing(
        batch_size=max(1, args.batch_size),
        sleep_seconds=max(0, args.sleep_seconds),
        dry_run=args.dry_run,
    )
    logger.info("Done. count=%d dry_run=%s", count, args.dry_run)


if __name__ == "__main__":
    main()
