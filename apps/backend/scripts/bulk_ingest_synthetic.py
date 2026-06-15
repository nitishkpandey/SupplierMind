"""
apps/backend/scripts/bulk_ingest_synthetic.py
Bulk-load `suppliers_synthetic_10k.json` into Postgres + Milvus.

Two-phase ingestion (separate so embedding failure doesn't lose PG data):
  Phase 1  Insert all rows into Postgres (sync, batches of 500).
  Phase 2  Embed via Voyage (batches of 128, 20s sleep ≥ 3 RPM) and
           insert vectors into Milvus. Checkpointed to a JSON file so
           interruptions resume cleanly.

Usage:
    cd apps/backend
    uv run python scripts/bulk_ingest_synthetic.py
    # Optional: --skip-pg if Postgres rows already inserted
    # Optional: --resume to continue from checkpoint
    # Optional: --input <path> to use a different JSON file

Idempotency: rows already in Postgres (matched by id) are skipped.
             Milvus phase processes only ids that are not yet indexed
             (according to the checkpoint).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from pathlib import Path

# Make ``app`` importable when invoked from /backend.
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.vector_store import (  # noqa: E402
    create_vector_store,
    set_vector_store_instance,
)
from app.db.models import Supplier  # noqa: E402
from app.db.session import SyncSessionLocal  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_INPUT = (
    Path(__file__).parent.parent / "data" / "suppliers_synthetic_10k.json"
)
CHECKPOINT_PATH = (
    Path(__file__).parent.parent / "data" / "bulk_ingest_checkpoint.json"
)

PG_BATCH = 500
# Voyage free tier: 3 RPM AND 10K TPM. Per-supplier text averages ~97 tokens
# (measured), so batch=80 -> ~7,760 TPM (safe) and sleep=55s -> ~1.09 RPM.
VOYAGE_BATCH = 80
VOYAGE_SLEEP_SECONDS = 55


# ── Helpers ──────────────────────────────────────────────────────────


def _load_records(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    logger.info("Loaded %d records from %s", len(records), path)
    return records


def _load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        with open(CHECKPOINT_PATH, encoding="utf-8") as f:
            cp = json.load(f)
        logger.info(
            "Checkpoint loaded: pg_done=%s, milvus_next_index=%d",
            cp.get("pg_done"), cp.get("milvus_next_index", 0),
        )
        return cp
    return {"pg_done": False, "milvus_next_index": 0}


def _save_checkpoint(cp: dict) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump(cp, f, indent=2)


def _supplier_from_raw(raw: dict) -> Supplier:
    """Build a Supplier ORM row from the synthetic JSON record."""
    return Supplier(
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
        source="synthetic_10k",
    )


# ── Phase 1: Postgres ────────────────────────────────────────────────


def phase_postgres(records: list[dict]) -> int:
    """Insert records into Postgres in batches of PG_BATCH.

    Idempotent: rows whose id already exists are skipped.
    Returns the count of newly inserted rows.
    """
    inserted = 0
    skipped = 0
    failed = 0
    start = time.time()

    for batch_start in range(0, len(records), PG_BATCH):
        batch = records[batch_start : batch_start + PG_BATCH]
        ids = [uuid.UUID(r["id"]) for r in batch]

        with SyncSessionLocal() as db:
            existing_rows = db.execute(
                select(Supplier.id).where(Supplier.id.in_(ids))
            ).all()
            existing_ids = {row[0] for row in existing_rows}

            to_insert = [r for r in batch if uuid.UUID(r["id"]) not in existing_ids]
            skipped += len(batch) - len(to_insert)

            for raw in to_insert:
                try:
                    db.add(_supplier_from_raw(raw))
                except Exception as e:
                    failed += 1
                    logger.error("DB build failed for %s: %s", raw.get("name"), e)
            try:
                db.commit()
                inserted += len(to_insert)
            except Exception as e:
                db.rollback()
                failed += len(to_insert)
                logger.error("Batch commit failed (rows %d-%d): %s",
                             batch_start, batch_start + len(batch), e)

        if (batch_start // PG_BATCH) % 5 == 0:
            logger.info(
                "Postgres progress: %d/%d (inserted=%d, skipped=%d, failed=%d)",
                batch_start + len(batch), len(records), inserted, skipped, failed,
            )

    elapsed = time.time() - start
    logger.info(
        "Postgres phase complete: inserted=%d skipped=%d failed=%d (%.1fs)",
        inserted, skipped, failed, elapsed,
    )
    return inserted


# ── Phase 2: Milvus ─────────────────────────────────────────────────


def phase_milvus(records: list[dict], start_index: int) -> int:
    """Embed and insert into Milvus in batches of VOYAGE_BATCH.

    Sleeps VOYAGE_SLEEP_SECONDS between batches to stay below 3 RPM.
    Checkpoints after each successful batch so the run is resumable.
    """
    vector_store = create_vector_store()
    set_vector_store_instance(vector_store)
    initial_count = vector_store.count()
    logger.info("Milvus initial entity count: %d", initial_count)

    total = len(records)
    total_batches = (total + VOYAGE_BATCH - 1) // VOYAGE_BATCH
    indexed_total = 0
    start_time = time.time()

    for batch_start in range(start_index, total, VOYAGE_BATCH):
        batch = records[batch_start : batch_start + VOYAGE_BATCH]
        batch_num = batch_start // VOYAGE_BATCH + 1

        try:
            vector_store.add_suppliers(batch)
            indexed_total += len(batch)
        except Exception as e:
            logger.error(
                "Milvus batch %d (rows %d-%d) FAILED: %s",
                batch_num, batch_start, batch_start + len(batch), e,
            )
            # Re-save checkpoint at the failed batch so resume retries it.
            _save_checkpoint({
                "pg_done": True,
                "milvus_next_index": batch_start,
            })
            raise

        next_index = batch_start + len(batch)
        _save_checkpoint({"pg_done": True, "milvus_next_index": next_index})

        elapsed = time.time() - start_time
        remaining = total_batches - batch_num
        eta_seconds = remaining * VOYAGE_SLEEP_SECONDS
        logger.info(
            "Milvus batch %d/%d: indexed %d (cumulative %d) | elapsed=%.0fs eta=%.0fs",
            batch_num, total_batches, len(batch), indexed_total,
            elapsed, eta_seconds,
        )

        # Last batch — no sleep needed.
        if next_index < total:
            time.sleep(VOYAGE_SLEEP_SECONDS)

    final_count = vector_store.count()
    logger.info(
        "Milvus phase complete: indexed=%d (collection %d -> %d)",
        indexed_total, initial_count, final_count,
    )
    return indexed_total


# ── Verification ────────────────────────────────────────────────────


def verify(records: list[dict]) -> None:
    """Print Postgres + Milvus counts for sanity-check."""
    with SyncSessionLocal() as db:
        from sqlalchemy import func
        pg_total = db.execute(select(func.count()).select_from(Supplier)).scalar_one()
        pg_approved = db.execute(
            select(func.count())
            .select_from(Supplier)
            .where(Supplier.status == "approved")
        ).scalar_one()
        pg_by_category = db.execute(
            select(Supplier.category, func.count())
            .where(Supplier.source == "synthetic_10k")
            .group_by(Supplier.category)
        ).all()

    try:
        vs = create_vector_store()
        milvus_count = vs.count()
    except Exception as e:
        logger.error("Could not query Milvus: %s", e)
        milvus_count = -1

    print("\n========== VERIFICATION ==========")
    print(f"Records in JSON   : {len(records)}")
    print(f"Postgres total    : {pg_total}")
    print(f"Postgres approved : {pg_approved}")
    print(f"Milvus entities   : {milvus_count}")
    print(f"\nNew synthetic rows by category:")
    for cat, n in sorted(pg_by_category, key=lambda x: -x[1]):
        print(f"  {cat:<28} {n:>6}")
    print("==================================\n")


# ── CLI ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument(
        "--skip-pg",
        action="store_true",
        help="Skip the Postgres phase (use if rows already inserted).",
    )
    parser.add_argument(
        "--skip-milvus",
        action="store_true",
        help="Skip the Milvus phase (debugging only).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume Milvus phase from checkpoint instead of starting from 0.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Print PG + Milvus counts and exit.",
    )
    args = parser.parse_args()

    records = _load_records(args.input)

    if args.verify_only:
        verify(records)
        return

    checkpoint = _load_checkpoint()

    # Phase 1: Postgres
    if args.skip_pg or checkpoint.get("pg_done"):
        logger.info("Skipping Postgres phase (already complete or --skip-pg).")
    else:
        phase_postgres(records)
        checkpoint["pg_done"] = True
        _save_checkpoint(checkpoint)

    # Phase 2: Milvus
    if args.skip_milvus:
        logger.info("Skipping Milvus phase (--skip-milvus).")
    else:
        start_index = checkpoint.get("milvus_next_index", 0) if args.resume else 0
        if start_index >= len(records):
            logger.info("Milvus phase already complete (checkpoint at end).")
        else:
            if start_index > 0:
                logger.info("Resuming Milvus phase from index %d", start_index)
            phase_milvus(records, start_index)

    verify(records)


if __name__ == "__main__":
    main()
