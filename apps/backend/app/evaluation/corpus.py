"""Benchmark corpus helpers.

Production searches can use the full active supplier database. Thesis
evaluation is different: SupplierBench metrics must stay bound to the frozen
curated corpus, even when the product database also contains the 10k scale set
or web-discovered pending-review suppliers.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

BENCHMARK_SUPPLIERS_FILE = (
    Path(__file__).resolve().parents[2] / "data" / "suppliers_synthetic.json"
)


@lru_cache(maxsize=1)
def benchmark_supplier_ids() -> frozenset[str]:
    """Return the frozen curated supplier IDs used for SupplierBench scoring."""
    with open(BENCHMARK_SUPPLIERS_FILE, encoding="utf-8") as f:
        suppliers = json.load(f)
    return frozenset(str(row["id"]) for row in suppliers if row.get("id"))
