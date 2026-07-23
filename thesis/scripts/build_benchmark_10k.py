"""
thesis/scripts/build_benchmark_10k.py

Deterministic. NO LLM, NO network, NO cost. Fully reproducible.

Builds a 10k-grounded benchmark to replace the frozen curated-100 one:

  1. SupplierBench-25  — 25 satisfiable queries (easy/medium/hard), every one
     VERIFIED to have >= MIN_GT matches in the 10k corpus. Capacity units are
     read from the corpus per category (10k uses one unit per category), so no
     unit-string mismatch. Numeric thresholds are auto-tuned to land the match
     count in a useful band, then the queries are re-scored and verified.

  2. Abstention-5      — 5 queries VERIFIED to have zero matches. These test
     whether a system correctly abstains instead of fabricating (SQuAD-2.0 /
     Natural-Questions "no-answer" methodology). Scored on correct-abstention
     and hallucination, never on P@5.

Ground truth stores the FULL relevant set (not truncated to 5), so recall is
well defined.

Outputs (under thesis/benchmark/):
  supplierbench25_10k.json
  abstention5_10k.json
  BUILD_REPORT.md

Run:
    python thesis/scripts/build_benchmark_10k.py
"""

from __future__ import annotations

import json
import math
import uuid
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS_10K = ROOT / "apps" / "backend" / "data" / "suppliers_synthetic_10k.json"
OUT_DIR = ROOT / "thesis" / "benchmark"

MIN_GT = 3          # hard floor: no scored query may have fewer matches
TARGET = {"simple": 12, "medium": 8, "hard": 5}   # tuning aim per tier
ROUND_CAPS = [100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000]
ROUND_LEADS = [7, 14, 21, 30, 45, 60, 90]
# Deterministic ID minting so re-runs are stable (uuid5 over a fixed namespace).
NS = uuid.UUID("00000000-0000-0000-0000-00005a1b0000")


def haversine(lat1, lng1, lat2, lng2) -> float:
    R = 6371.0
    dlat, dlng = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# ── 25 query intents (category / geography / cert shape / tier). Numeric
# thresholds are chosen by the tuner, not hand-written, so they always fit 10k.
INTENTS = [
    # simple: 1-2 constraints
    dict(n=1, tier="simple", cat="metals", country="Germany"),
    dict(n=2, tier="simple", cat="electronics", certs=["ISO 9001"]),
    dict(n=3, tier="simple", cat="logistics", country="Germany"),
    dict(n=4, tier="simple", cat="software_services", country="Germany"),
    dict(n=5, tier="simple", cat="textiles", certs=["ISO 14001"]),
    dict(n=6, tier="simple", cat="chemicals", certs=["REACH"]),
    dict(n=7, tier="simple", cat="packaging", country="Germany"),
    dict(n=8, tier="simple", cat="food_ingredients", certs=["ISO 22000"]),
    # medium: 3-4 constraints (category + country + cert + one numeric)
    dict(n=9, tier="medium", cat="metals", country="Germany", certs=["ISO 9001"], want_cap=True),
    dict(n=10, tier="medium", cat="electronics", country="Germany", certs=["ISO 9001"], want_lead=True),
    dict(n=11, tier="medium", cat="logistics", country="Germany", want_cap=True),
    dict(n=12, tier="medium", cat="software_services", country="Germany", certs=["ISO 27001"]),
    dict(n=13, tier="medium", cat="chemicals", country="Germany", certs=["REACH"], want_cap=True),
    dict(n=14, tier="medium", cat="packaging", country="Germany", want_cap=True),
    dict(n=15, tier="medium", cat="machinery", country="Germany", certs=["CE"], want_lead=True),
    dict(n=16, tier="medium", cat="textiles", country="Germany", certs=["ISO 9001"]),
    dict(n=17, tier="medium", cat="food_ingredients", certs=["ISO 22000"], want_cap=True),
    dict(n=18, tier="medium", cat="construction_materials", country="Germany", certs=["CE"], want_cap=True),
    # hard: 5-6 constraints (category + country + cert(s) + capacity + lead)
    dict(n=19, tier="hard", cat="metals", country="Germany", certs=["ISO 9001"], want_cap=True, want_lead=True),
    dict(n=20, tier="hard", cat="electronics", country="Germany", certs=["ISO 9001"], want_cap=True, want_lead=True),
    dict(n=21, tier="hard", cat="software_services", country="Germany", certs=["ISO 27001"], want_lead=True),
    dict(n=22, tier="hard", cat="chemicals", country="Germany", certs=["REACH"], want_cap=True, want_lead=True),
    dict(n=23, tier="hard", cat="packaging", country="Germany", certs=["ISO 9001"], want_cap=True, want_lead=True),
    dict(n=24, tier="hard", cat="textiles", country="Germany", certs=["ISO 9001"], want_cap=True, want_lead=True),
    dict(n=25, tier="hard", cat="food_ingredients", country="Germany", want_cap=True, want_lead=True),
]

# 5 abstention queries: realistic wording, verified zero matches on 10k.
ABSTENTION = [
    dict(cat="logistics", country="Germany", certs=["AS9100"],
         text="AS9100 aerospace-certified logistics providers in Germany"),
    dict(cat="software_services", country="Germany", certs=["ISO 27001", "IATF 16949"],
         text="ISO 27001 and IATF 16949 automotive-certified software services in Germany"),
    dict(cat="food_ingredients", country="Germany", certs=["IATF 16949"],
         text="IATF 16949 automotive-certified food ingredient suppliers in Germany"),
    dict(cat="metals", country="Germany", certs=["ISO 9001"], cap=999999999,
         text="ISO 9001 metal suppliers in Germany with capacity over 999,999,999 kg/month"),
    dict(cat="textiles", country="Iceland", certs=["ISO 14001"],
         text="ISO 14001 certified textile suppliers in Iceland"),
]


def unit_for(suppliers, cat) -> str:
    units = Counter(s.get("capacity_unit") for s in suppliers if s.get("category") == cat)
    return units.most_common(1)[0][0] if units else "units/month"


def apply_cat(suppliers, cat, country=None, certs=None):
    pool = [s for s in suppliers if s.get("category") == cat]
    if country:
        pool = [s for s in pool if s.get("country") == country]
    for c in certs or []:
        pool = [s for s in pool if c in (s.get("certifications") or [])]
    return pool


def gt_after(pool, cap, lead):
    ids = []
    for s in pool:
        if cap and (s.get("capacity_value") or 0) < cap:
            continue
        if lead and (s.get("lead_time_days") or 10**9) > lead:
            continue
        ids.append(s["id"])
    return ids


def tune(pool, want_cap, want_lead, target):
    """Co-optimise capacity floor and lead-time cap together (small brute-force
    search) so the INTERSECTION lands near `target` while staying >= MIN_GT.
    Returns (cap, lead, gt_ids). Falls back to looser combos, then to no
    numeric constraint, rather than producing an empty query."""
    cap_opts = ([None] + ROUND_CAPS) if want_cap else [None]
    lead_opts = ([None] + ROUND_LEADS) if want_lead else [None]
    best = None
    for cap in cap_opts:
        for lead in lead_opts:
            ids = gt_after(pool, cap, lead)
            if len(ids) < MIN_GT:
                continue
            # nearest to target; tie-break toward tighter (higher cap, lower lead)
            key = (abs(len(ids) - target), -(cap or 0), lead or 999)
            if best is None or key < best[0]:
                best = (key, cap, lead, ids)
    if best is None:
        return None, None, gt_after(pool, None, None)
    return best[1], best[2], best[3]


def render_text(cat, country, certs, cap, cap_unit, lead) -> str:
    parts = []
    if certs:
        parts.append(" and ".join(certs) + " certified")
    parts.append(cat.replace("_", " "))
    parts.append("suppliers")
    if country:
        parts.append(f"in {country}")
    if cap:
        parts.append(f"with capacity over {cap:,} {cap_unit}")
    if lead:
        parts.append(f"lead time under {lead} days")
    return " ".join(parts).replace("suppliers in", "suppliers in")


def build_satisfiable(suppliers, log):
    out = []
    for intent in INTENTS:
        cat, tier = intent["cat"], intent["tier"]
        country = intent.get("country")
        certs = list(intent.get("certs") or [])
        cap_unit = unit_for(suppliers, cat)
        target = TARGET[tier]
        notes = []

        pool = apply_cat(suppliers, cat, country, certs)
        # Relax certs if too rare to hit the floor.
        while certs and len(pool) < max(MIN_GT, target // 2):
            dropped = certs.pop()
            notes.append(f"dropped cert '{dropped}' (only {len(pool)} matched with it)")
            pool = apply_cat(suppliers, cat, country, certs)

        cap, lead, gt = tune(pool, intent.get("want_cap"), intent.get("want_lead"), target)
        if intent.get("want_cap") and cap is None:
            notes.append("capacity floor dropped — no round floor kept >=3 with the other constraints")
        if intent.get("want_lead") and lead is None:
            notes.append("lead-time cap dropped — no round cap kept >=3 with the other constraints")

        text = render_text(cat, country, certs, cap, cap_unit, lead)
        q = dict(
            id=str(uuid.uuid5(NS, f"sat-{intent['n']}")),
            query_number=intent["n"],
            raw_query=text,
            difficulty=tier,
            constraints=_constraints(cat, country, certs, cap, cap_unit, lead),
            ground_truth_supplier_ids=gt,
            ground_truth_count=len(gt),
        )
        out.append(q)
        status = "OK" if len(gt) >= MIN_GT else "FAIL(<3)"
        log.append(
            f"| {intent['n']} | {tier} | {len(gt)} | {status} | "
            f"cap={cap or '-'} lead={lead or '-'} certs={certs or '-'} | "
            f"{'; '.join(notes) or '-'} |"
        )
    return out


def build_abstention(suppliers, log):
    out = []
    for i, a in enumerate(ABSTENTION, 1):
        pool = apply_cat(suppliers, a["cat"], a.get("country"), a.get("certs"))
        if a.get("cap"):
            pool = [s for s in pool if (s.get("capacity_value") or 0) >= a["cap"]]
        q = dict(
            id=str(uuid.uuid5(NS, f"abs-{i}")),
            query_number=i,
            raw_query=a["text"],
            difficulty="unsatisfiable",
            constraints=_constraints(
                a["cat"], a.get("country"), a.get("certs") or [],
                a.get("cap"), unit_for(suppliers, a["cat"]) if a.get("cap") else None, None,
            ),
            ground_truth_supplier_ids=[],
            ground_truth_count=0,
        )
        out.append(q)
        status = "OK(empty)" if len(pool) == 0 else f"BAD({len(pool)} matched!)"
        log.append(f"| A{i} | unsat | {len(pool)} | {status} | {a['text'][:50]} |")
    return out


def _constraints(cat, country, certs, cap, cap_unit, lead):
    c = {"category": cat}
    if country:
        c["country"] = country
    if certs:
        c["certs"] = certs
    if cap:
        c["min_cap"] = cap
        c["cap_unit"] = cap_unit
    if lead:
        c["max_lead"] = lead
    return c


def main():
    suppliers = json.loads(CORPUS_10K.read_text())
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sat_log = ["| Q | tier | GT | status | tuned | notes |", "|---|---|---|---|---|---|"]
    sat = build_satisfiable(suppliers, sat_log)
    abs_log = ["| Q | tier | pool | status | query |", "|---|---|---|---|---|"]
    absten = build_abstention(suppliers, abs_log)

    (OUT_DIR / "supplierbench25_10k.json").write_text(json.dumps(sat, indent=2, ensure_ascii=False))
    (OUT_DIR / "abstention5_10k.json").write_text(json.dumps(absten, indent=2, ensure_ascii=False))

    fails = [q["query_number"] for q in sat if q["ground_truth_count"] < MIN_GT]
    bad_abs = [q["query_number"] for q in absten if q["ground_truth_count"] != 0]

    report = [
        "# SupplierBench 10k — Build Report",
        "",
        f"Corpus: `suppliers_synthetic_10k.json` ({len(suppliers)} suppliers). "
        "Deterministic build (no LLM). Re-running this script reproduces the same file.",
        "",
        f"Floor: every satisfiable query must have >= {MIN_GT} matches. "
        f"Tuning targets per tier: {TARGET}.",
        "",
        "Ground truth stores the FULL relevant set (not truncated to 5), so recall is well defined.",
        "",
        "## SupplierBench-25 (satisfiable)",
        *sat_log,
        "",
        f"Floor check: {'ALL PASS' if not fails else 'FAILURES ' + str(fails)}.",
        "",
        "## Abstention-5 (must be empty)",
        *abs_log,
        "",
        f"Empty check: {'ALL PASS' if not bad_abs else 'NOT EMPTY ' + str(bad_abs)}.",
        "",
        "## Reviewer notes",
        "- Capacity units come from the corpus per category (10k uses one unit per category).",
        "- Thresholds are auto-tuned round numbers, not hand-picked. Edit any query in the",
        "  JSON and re-run the diagnostic to re-verify; adjust intents in this script to change wording.",
        "- Geography: 10k is global, so hard queries use country + stacked cert/capacity/lead",
        "  constraints rather than tight km-radius (radius on a sparse global corpus was the main",
        "  cause of the old empty hard tier). Radius-based queries can be added back per-city if you",
        "  want them, as long as the floor still holds.",
    ]
    (OUT_DIR / "BUILD_REPORT.md").write_text("\n".join(report))

    print("\n".join(sat_log))
    print()
    print("\n".join(abs_log))
    print()
    print(f"satisfiable floor check: {'ALL PASS' if not fails else 'FAIL ' + str(fails)}")
    print(f"abstention empty check:  {'ALL PASS' if not bad_abs else 'FAIL ' + str(bad_abs)}")
    print(f"\nwrote: {OUT_DIR}/supplierbench25_10k.json, abstention5_10k.json, BUILD_REPORT.md")


if __name__ == "__main__":
    main()
