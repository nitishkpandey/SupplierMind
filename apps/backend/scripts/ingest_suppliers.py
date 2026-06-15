"""
backend/scripts/ingest_suppliers.py — CLI script to ingest SupplierBench data.

RUN THIS ONCE after Phase 1 setup:
    cd backend
    python scripts/ingest_suppliers.py

This populates both PostgreSQL and Milvus with all 100 synthetic suppliers.
After running, the system is ready for agent queries.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add backend/ to Python path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.core.vector_store import create_vector_store, set_vector_store_instance
from app.db.session import AsyncSessionLocal
from app.services.ingestion import ingest_suppliers_from_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    dataset_path = Path(__file__).parent.parent / "data" / "suppliers_synthetic.json"

    if not dataset_path.exists():
        logger.error(
            "Dataset not found at %s\n"
            "Run first: python data/generate_dataset.py",
            dataset_path,
        )
        sys.exit(1)

    logger.info("Initializing vector store (%s)...", settings.effective_vector_db)
    vector_store = create_vector_store()
    set_vector_store_instance(vector_store)
    logger.info("Vector store ready. Current count: %d", vector_store.count())

    logger.info("Starting supplier ingestion...")
    async with AsyncSessionLocal() as db:
        stats = await ingest_suppliers_from_json(db, dataset_path, batch_size=20)

    logger.info("=" * 50)
    logger.info("INGESTION COMPLETE")
    logger.info("  Inserted : %d", stats["inserted"])
    logger.info("  Skipped  : %d (already exists)", stats["skipped"])
    logger.info("  Failed   : %d", stats["failed"])
    logger.info("  Total in Milvus: %d", vector_store.count())
    logger.info("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
