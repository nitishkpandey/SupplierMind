"""
thesis/scripts/verify_milvus_10k.py

Pre-flight check before the paid benchmark run. Confirms the 10k benchmark's
ground-truth suppliers are actually present in the Milvus index, so P2/P3
retrieval can find them. Cheap: a few metadata queries, no embedding calls.

Needs Milvus up (docker compose ... up -d).

Run:
    cd apps/backend
    uv run python ../../thesis/scripts/verify_milvus_10k.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "apps" / "backend"
sys.path.insert(0, str(BACKEND))

BENCH = BACKEND.parent.parent / "thesis" / "benchmark" / "supplierbench25_10k.json"


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def main() -> None:
    from app.core.vector_store import create_vector_store

    vs = create_vector_store()
    total = vs.count()
    print(f"Milvus entity count: {total}")

    gt_ids = sorted({sid for q in json.loads(BENCH.read_text())
                     for sid in q.get("ground_truth_supplier_ids", [])})
    print(f"Unique ground-truth supplier IDs in the benchmark: {len(gt_ids)}")

    coll = getattr(vs, "_collection", None)
    if coll is None:
        print("Vector store is not Milvus-backed; skipping ID presence check.")
        return

    present = set()
    for batch in chunks(gt_ids, 200):
        expr = "supplier_id in [" + ", ".join(f'"{s}"' for s in batch) + "]"
        rows = coll.query(expr=expr, output_fields=["supplier_id"])
        present.update(r["supplier_id"] for r in rows)

    missing = [s for s in gt_ids if s not in present]
    print(f"Ground-truth IDs found in Milvus: {len(present)}/{len(gt_ids)}")
    if missing:
        print(f"MISSING {len(missing)} — retrieval will miss these. First few: {missing[:5]}")
        print("Re-index before running the benchmark (bulk_ingest_synthetic.py --skip-pg --resume).")
        sys.exit(1)
    print("OK — every benchmark ground-truth supplier is indexed. Safe to run the benchmark.")


if __name__ == "__main__":
    main()
