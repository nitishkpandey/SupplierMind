"""
thesis/scripts/analyze_results.py

Deterministic. NO LLM, NO network, NO cost. Runs on any evaluation_results.json.

Computes the *new* thesis metrics that the stock runner does not report:

  1. answer_rate        — fraction of queries the system returned anything for.
                          (Separates "returned wrong suppliers" from "returned
                          nothing" — the whole reason P3's CSR looked low.)
  2. recall@k           — of the true relevant suppliers, how many were found.
                          (Stock harness has precision only.)
  3. gate_accuracy (P3) — of P3's per-constraint PASS/FAIL verdicts, how many
                          are actually TRUE against the corpus record, overall
                          and per constraint type. Plus PASS precision/recall.
                          This is the mechanism-level test of the reframed H1:
                          does the agentic verification actually verify?
  4. entity_hallucination (P1) — fraction of names P1 emitted that do not exist
                          in the corpus (parametric fabrication).

Defaults point at the committed curated-100 run so you can see it work today;
pass --results/--corpus/--benchmark to run it on the 10k results later.

Run:
    python thesis/scripts/analyze_results.py
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "backend"


def haversine(lat1, lng1, lat2, lng2) -> float:
    R = 6371.0
    dlat, dlng = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def norm_name(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def true_verdict(cname, sup, c):
    """Ground-truth verdict for one constraint against the corpus record.
    Returns True / False / None (cannot determine from structured query)."""
    if cname == "product_fit":
        return sup.get("category") == c.get("category") if c.get("category") else None
    if cname == "country":
        return sup.get("country") == c.get("country") if c.get("country") else None
    if cname == "capacity":
        if not (c.get("min_cap") and c.get("cap_unit")):
            return None
        if sup.get("capacity_unit") != c["cap_unit"]:
            return False
        return (sup.get("capacity_value") or 0) >= c["min_cap"]
    if cname == "lead_time":
        if not c.get("max_lead"):
            return None
        return (sup.get("lead_time_days") or 10**9) <= c["max_lead"]
    if cname == "location_radius":
        center, radius = c.get("center"), c.get("radius_km")
        if not (center and radius and sup.get("latitude")):
            return None
        return haversine(center[0], center[1], sup["latitude"], sup["longitude"]) <= radius
    # otherwise a certification name
    return cname in (sup.get("certifications") or [])


def convert(c: dict) -> dict:
    """Benchmark constraint keys → the keys true_verdict expects."""
    out = dict(c)
    if "certs" in out:
        out["certs"] = out["certs"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(ROOT / "results" / "run_20260710" / "evaluation_results.json"))
    ap.add_argument("--corpus", default=str(BACKEND / "data" / "suppliers_synthetic.json"))
    ap.add_argument("--benchmark", default=str(BACKEND / "data" / "queries_benchmark.json"))
    ap.add_argument("-k", type=int, nargs="+", default=[5, 10])
    args = ap.parse_args()

    results = json.loads(Path(args.results).read_text())
    corpus = {str(s["id"]): s for s in json.loads(Path(args.corpus).read_text())}
    bench = {q["id"]: q for q in json.loads(Path(args.benchmark).read_text())}
    names_norm = {norm_name(s["name"]): sid for sid, s in corpus.items()}

    pq = results["per_query_metrics"]

    print("=" * 72)
    print(f"Analyzing: {Path(args.results).parent.name}  ({len(corpus)}-supplier corpus)")
    print("=" * 72)

    # ── 1 & 2: answer rate + recall@k, per system ─────────────────────────
    print(f"\n{'system':<20}{'answer_rate':>12}" + "".join(f"{f'recall@{k}':>11}" for k in args.k))
    print("-" * 72)
    for system, rows in pq.items():
        if not rows:
            continue
        answered = sum(1 for q in rows if q.get("retrieved_ids"))
        recalls = {k: [] for k in args.k}
        for q in rows:
            gt = set(q.get("ground_truth_ids") or [])
            if not gt:
                continue  # recall undefined with no relevant set
            ret = q.get("retrieved_ids") or []
            for k in args.k:
                hits = len(gt & set(ret[:k]))
                recalls[k].append(hits / len(gt))
        rec_str = "".join(
            f"{(sum(recalls[k])/len(recalls[k]) if recalls[k] else 0):>11.3f}" for k in args.k
        )
        print(f"{system:<20}{answered/len(rows):>12.3f}{rec_str}")

    # ── 2b: P3 clarification (ask) rate ───────────────────────────────────
    sm = pq.get("suppliermind", [])
    if sm and any(q.get("would_clarify") is not None for q in sm):
        asked_tier: dict[str, int] = defaultdict(int)
        total_tier: dict[str, int] = defaultdict(int)
        asked = 0
        for q in sm:
            total_tier[q["difficulty"]] += 1
            if q.get("would_clarify"):
                asked += 1
                asked_tier[q["difficulty"]] += 1
        print(f"\nP3 clarification (ask) rate: {asked}/{len(sm)} = {asked / len(sm):.3f}")
        for t in ("simple", "medium", "hard"):
            if total_tier[t]:
                print(f"  {t:8} {asked_tier[t]}/{total_tier[t]}")

    # ── 3: P3 compliance-gate accuracy ────────────────────────────────────
    per_type = defaultdict(lambda: {"correct": 0, "total": 0})
    tp = fp = fn = 0  # PASS as the positive prediction
    for q in sm:
        c = convert(bench.get(q["query_id"], {}).get("constraints", {}))
        for sup in (q.get("compliance_data") or []):
            rec = corpus.get(str(sup["supplier_id"]))
            if not rec:
                continue
            for chk in sup.get("compliance_results", []):
                cname, status = chk["constraint_name"], chk["status"]
                truth = true_verdict(cname, rec, c)
                if truth is None:
                    continue
                ctype = cname if cname in {"product_fit", "country", "capacity", "lead_time", "location_radius"} else "certification"
                predicted_pass = status == "PASS"
                correct = predicted_pass == truth  # PARTIAL treated as not-PASS
                per_type[ctype]["total"] += 1
                per_type[ctype]["correct"] += int(correct)
                if predicted_pass and truth:
                    tp += 1
                elif predicted_pass and not truth:
                    fp += 1
                elif (not predicted_pass) and truth:
                    fn += 1

    print("\nP3 compliance-gate accuracy (verdict vs. corpus truth):")
    print(f"  {'constraint type':<18}{'accuracy':>10}{'n':>7}")
    tot_c = tot_n = 0
    for ctype, d in sorted(per_type.items()):
        tot_c += d["correct"]; tot_n += d["total"]
        print(f"  {ctype:<18}{d['correct']/d['total']:>10.3f}{d['total']:>7}")
    if tot_n:
        print(f"  {'OVERALL':<18}{tot_c/tot_n:>10.3f}{tot_n:>7}")
    prec = tp / (tp + fp) if (tp + fp) else 0
    rec = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0
    print(f"  PASS-verdict precision={prec:.3f}  recall={rec:.3f}  F1={f1:.3f}")

    # ── 3b: P3 evidence quotes (fabrication / verifiability) ──────────────
    claims_with_quote = 0
    flags = defaultdict(int)
    pass_partial_claims = 0
    for q in sm:
        for sup in (q.get("compliance_data") or []):
            for chk in sup.get("compliance_results", []):
                if chk.get("status") in ("PASS", "PARTIAL"):
                    pass_partial_claims += 1
                if chk.get("evidence_quote"):
                    claims_with_quote += 1
                if chk.get("quote_flag"):
                    flags[chk["quote_flag"]] += 1
    print("\nP3 evidence quotes (LLM compliance path):")
    if pass_partial_claims:
        print(f"  PASS/PARTIAL claims: {pass_partial_claims}; "
              f"carrying a verbatim quote: {claims_with_quote}")
        if flags:
            fab = flags.get("quote_not_in_source", 0)
            print(f"  fabricated quotes (quote_not_in_source): {fab}")
            print(f"  all quote flags: {dict(flags)}")
        else:
            print("  no unverifiable/fabricated quote flags in this run")
    else:
        print("  (no compliance claims in this run)")
    if claims_with_quote == 0:
        print("  note: verdicts here were deterministic field matches (no quote to fabricate)")

    # ── 4: P1 entity hallucination ────────────────────────────────────────
    p1 = pq.get("p1_singleprompt", [])
    total_names = resolved = 0
    for q in p1:
        for nm in (q.get("raw_names") or []):
            total_names += 1
            if norm_name(nm) in names_norm:
                resolved += 1
    if total_names:
        print(f"\nP1 entity-hallucination rate: {1 - resolved/total_names:.3f} "
              f"({total_names - resolved}/{total_names} emitted names not in corpus)")


if __name__ == "__main__":
    main()
