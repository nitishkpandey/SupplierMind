"""
thesis/scripts/dedupe_milvus.py

The bulk re-ingest appends vectors (Milvus does not upsert), so an interrupted
re-run can leave a supplier with several identical vectors. Duplicates waste
top-k slots at search time and bias retrieval for the affected suppliers only.

This removes the extras WITHOUT re-embedding: the collection has an auto INT64
primary key `pk`, so we keep the lowest pk per supplier_id and delete the rest.
Free and fast.

Dry-run by default (reports only). Pass --apply to actually delete.

Run:
    cd apps/backend
    uv run python ../../thesis/scripts/dedupe_milvus.py          # report
    uv run python ../../thesis/scripts/dedupe_milvus.py --apply   # fix
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "backend"))


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually delete duplicates")
    args = ap.parse_args()

    from app.core.vector_store import create_vector_store

    vs = create_vector_store()
    coll = getattr(vs, "_collection", None)
    if coll is None:
        raise SystemExit("Not a Milvus-backed store; nothing to dedupe.")

    total = vs.count()
    rows = coll.query(expr="pk >= 0", output_fields=["pk", "supplier_id"], limit=16384)
    if len(rows) < total:
        print(f"WARNING: read {len(rows)} of {total} rows (query cap). Re-run with pagination.")

    by_sid: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        by_sid[r["supplier_id"]].append(int(r["pk"]))

    extra_pks: list[int] = []
    dup_suppliers = 0
    for sid, pks in by_sid.items():
        if len(pks) > 1:
            dup_suppliers += 1
            extra_pks.extend(sorted(pks)[1:])  # keep the lowest pk

    print(f"Total vectors:        {total}")
    print(f"Unique supplier_ids:  {len(by_sid)}")
    print(f"Suppliers with dupes: {dup_suppliers}")
    print(f"Extra vectors to drop: {len(extra_pks)}")

    if not extra_pks:
        print("No duplicates. Index is clean.")
        return
    if not args.apply:
        print("\nDry run. Re-run with --apply to delete the extras.")
        return

    for batch in chunks(extra_pks, 500):
        coll.delete(f"pk in [{', '.join(str(p) for p in batch)}]")
    coll.flush()
    print(f"\nDeleted {len(extra_pks)} duplicate vectors. New count: {vs.count()}")


if __name__ == "__main__":
    main()
