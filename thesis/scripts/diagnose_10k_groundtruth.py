"""
thesis/scripts/diagnose_10k_groundtruth.py

Deterministic diagnostic. NO LLM, NO network, NO cost.

Question it answers: if we rebuild the SupplierBench ground truth against the
10,000-supplier corpus using the *existing* 25 query templates, how many
suppliers match each query, and for the empty ones, which constraint zeroed it?

This tells us exactly what has to change before a 10k-grounded benchmark is
scoreable (unit vocabulary, geography, constraint tightness).

Run:
    cd apps/backend
    uv run python ../../thesis/scripts/diagnose_10k_groundtruth.py
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "apps" / "backend"
CORPUS_10K = BACKEND / "data" / "suppliers_synthetic_10k.json"
QUERIES = BACKEND / "data" / "queries_benchmark.json"


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def match_with_reasons(suppliers: list[dict], c: dict) -> tuple[list[str], Counter]:
    """Return matching ids and a counter of which single constraint eliminated
    each non-matching supplier that was in the right category (first-fail)."""
    ids: list[str] = []
    killed = Counter()
    category = c.get("category")
    country = c.get("country")
    certs = c.get("certs") or []
    min_cap = c.get("min_cap")
    cap_unit = c.get("cap_unit")
    max_lead = c.get("max_lead")
    center = c.get("center")
    radius_km = c.get("radius_km")

    for s in suppliers:
        if category and s.get("category") != category:
            continue  # wrong category is not an interesting "kill reason"
        # now we're in-category; find first failing constraint
        if country and s.get("country") != country:
            killed["country"] += 1
            continue
        if certs and not all(cert in (s.get("certifications") or []) for cert in certs):
            killed["certs"] += 1
            continue
        if min_cap and cap_unit:
            if s.get("capacity_unit") != cap_unit:
                killed["cap_unit_mismatch"] += 1
                continue
            if (s.get("capacity_value") or 0) < min_cap:
                killed["cap_below_min"] += 1
                continue
        if max_lead and (s.get("lead_time_days") or 10**9) > max_lead:
            killed["lead_time"] += 1
            continue
        if center and radius_km:
            d = haversine(center[0], center[1], s.get("latitude", 0), s.get("longitude", 0))
            if d > radius_km:
                killed["radius"] += 1
                continue
        ids.append(s["id"])
    return ids, killed


def main() -> None:
    suppliers = json.loads(CORPUS_10K.read_text())
    queries = json.loads(QUERIES.read_text())

    # Category -> capacity units actually present in 10k (adaptation aid).
    cat_units: dict[str, Counter] = defaultdict(Counter)
    cat_countries: dict[str, Counter] = defaultdict(Counter)
    for s in suppliers:
        cat_units[s.get("category")][s.get("capacity_unit")] += 1
        cat_countries[s.get("category")][s.get("country")] += 1

    print("=" * 78)
    print(f"10k corpus: {len(suppliers)} suppliers")
    print("Capacity unit vocabulary present per category (count):")
    for cat in sorted(cat_units):
        units = ", ".join(f"{u}:{n}" for u, n in cat_units[cat].most_common())
        print(f"  {cat:24s} {units}")
    print("=" * 78)

    print(f"\nPorting the {len(queries)} existing templates onto 10k (exact matching):\n")
    print(f"{'Q':>3} {'tier':7} {'matches':>7}  first-fail reasons / note")
    print("-" * 78)
    empty = []
    for q in queries:
        c = q["constraints"]
        ids, killed = match_with_reasons(suppliers, c)
        note = ""
        if not ids:
            empty.append(q["query_number"])
            # what unit does this query ask for vs what exists in the category?
            asked_unit = c.get("cap_unit")
            have = set(cat_units.get(c.get("category"), {}))
            if asked_unit and asked_unit not in have:
                note = f"UNIT '{asked_unit}' absent in 10k (have: {sorted(have)})"
            else:
                note = "; ".join(f"{k}={v}" for k, v in killed.most_common(3))
        print(f"{q['query_number']:>3} {q['difficulty']:7} {len(ids):>7}  {note}")

    print("-" * 78)
    print(f"Empty-GT queries on 10k with current templates: {len(empty)} -> {empty}")
    print("(These are the queries that need constraint/unit/geography adaptation.)")


if __name__ == "__main__":
    main()
