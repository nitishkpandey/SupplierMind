"""Seed explicit source-cited demo suppliers into PostgreSQL and the vector store."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.vector_store import (  # noqa: E402
    create_vector_store,
    set_vector_store_instance,
)
from app.db.session import SyncSessionLocal  # noqa: E402
from app.services.demo_seed import load_demo_records, seed_demo_suppliers  # noqa: E402

logger = logging.getLogger(__name__)
DEMO_FIXTURE = BACKEND_ROOT / "demo" / "german_breweries.json"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    records = load_demo_records(DEMO_FIXTURE)
    vector_store = create_vector_store()
    set_vector_store_instance(vector_store)

    with SyncSessionLocal() as db:
        stats = seed_demo_suppliers(db, vector_store, records)

    logger.info(
        "Demo supplier seed complete: inserted=%d updated=%d indexed=%d",
        stats.inserted,
        stats.updated,
        stats.indexed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
