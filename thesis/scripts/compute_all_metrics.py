"""
thesis/scripts/compute_all_metrics.py

Deterministic (fixed bootstrap seed). NO LLM, NO cost. Reads the archived 10k
runs and produces the FULL metric suite for the thesis in one place:

  quality      P@5, MRR, Recall@5/10, nDCG@5, MAP@5, Success@1, answer-rate
  constraints  CSR (as-scored) + harmonized CSR (P3 re-scored with P2's scorer)
  trust        compliance-gate accuracy (P3), entity-hallucination (P1)
  behavior     clarification (ask) rate (P3), per-tier P@5
  cost/ops     cost/query, cost-per-correct, latency (raw + pacing-minimized)
  rigor        bootstrap 95% CIs, paired P3-vs-P2 significance test

Metrics that vary run-to-run are reported as the mean over runs; ranking
metrics are computed per run then averaged. CIs and the significance test use
query-level means (one value per query) so they reflect query-difficulty
spread, matching standard IR practice.

Run:
    python thesis/scripts/compute_all_metrics.py
    python thesis/scripts/compute_all_metrics.py --dir thesis/results/10k
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import random
import statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "backend"
SEED = 42
N_BOOT = 10000
SYSTEMS = ["suppliermind", "p2_rag", "p1_singleprompt"]
LABELS = {"suppliermind": "P3 SupplierMind", "p2_rag": "P2 RAG", "p1_singleprompt": "P1 single-prompt"}


# ── ranking metrics from retrieved_ids + ground truth ────────────────────
def precision_at_k(ret, rel, k=5):
    return sum(1 for r in ret[:k] if r in rel) / k if ret else 0.0

def recall_at_k(ret, rel, k):
    return (sum(1 for r in ret[:k] if r in rel) / len(rel)) if rel else 0.0

def rr(ret, rel):
    for i, r in enumerate(ret[:5]):
        if r in rel:
            return 1.0 / (i + 1)
    return 0.0

def success_at_1(ret, rel):
    return 1.0 if ret and ret[0] in rel else 0.0

def ndcg_at_k(ret, rel, k=5):
    dcg = sum((1.0 / math.log2(i + 2)) for i, r in enumerate(ret[:k]) if r in rel)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(k, len(rel))))
    return dcg / ideal if ideal else 0.0

def ap_at_k(ret, rel, k=5):
    if not rel:
        return 0.0
    hits, score = 0, 0.0
    for i, r in enumerate(ret[:k]):
        if r in rel:
            hits += 1
            score += hits / (i + 1)
    return score / min(len(rel), k)


# ── harmonized CSR: P2's profile scorer applied to any system's picks ────
def convert_constraints(c):
    out = {"category": c.get("category")}
    if c.get("certs"):
        out["certifications"] = c["certs"]
    if c.get("min_cap"):
        out["capacity_min"] = c["min_cap"]
        out["capacity_unit"] = c.get("cap_unit")
    if c.get("max_lead"):
        out["lead_time_max_days"] = c["max_lead"]
    if c.get("center"):
        out["location_lat"], out["location_lng"] = c["center"]
        out["location_radius_km"] = c.get("radius_km")
    return out

def _haversine(a, b, x, y):
    R = 6371.0
    dlat, dlng = math.radians(x - a), math.radians(y - b)
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a)) * math.cos(math.radians(x)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(h))

def csr_profile(records, c):
    """Same logic as app.evaluation.metrics.constraint_satisfaction_rate_from_suppliers."""
    if not records or not c:
        return 0.0
    rates = []
    for s in records[:5]:
        checks = []
        if c.get("category") and s.get("category"):
            checks.append(1.0 if s["category"] == c["category"] else 0.0)
        scerts = [x.upper() for x in (s.get("certifications") or [])]
        for rc in (c.get("certifications") or []):
            checks.append(1.0 if rc.upper() in scerts else 0.0)
        if c.get("capacity_min") and c.get("capacity_unit"):
            cap, unit = s.get("capacity_value"), s.get("capacity_unit", "")
            if cap is None or unit != c["capacity_unit"]:
                checks.append(0.5)
            elif cap >= c["capacity_min"]:
                checks.append(1.0)
            elif cap >= c["capacity_min"] * 0.8:
                checks.append(0.5)
            else:
                checks.append(0.0)
        if c.get("lead_time_max_days"):
            lt = s.get("lead_time_days")
            checks.append(0.5 if lt is None else (1.0 if lt <= c["lead_time_max_days"] else 0.0))
        if c.get("location_lat") and c.get("location_radius_km") and s.get("latitude"):
            d = _haversine(c["location_lat"], c["location_lng"], s["latitude"], s["longitude"])
            checks.append(1.0 if d <= c["location_radius_km"] else (0.5 if d <= c["location_radius_km"] * 1.1 else 0.0))
        rates.append(st.mean(checks) if checks else 1.0)
    return st.mean(rates) if rates else 0.0


# ── gate accuracy (P3 verdict vs corpus truth) ───────────────────────────
def true_verdict(cname, sup, c):
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
        return None if not c.get("max_lead") else (sup.get("lead_time_days") or 1e9) <= c["max_lead"]
    if cname == "location_radius":
        if not (c.get("center") and c.get("radius_km") and sup.get("latitude")):
            return None
        return _haversine(c["center"][0], c["center"][1], sup["latitude"], sup["longitude"]) <= c["radius_km"]
    return cname in (sup.get("certifications") or [])


def bootstrap_ci(values, n=N_BOOT):
    if not values:
        return (0.0, 0.0)
    rng = random.Random(SEED)
    m = len(values)
    means = sorted(st.mean(values[rng.randrange(m)] for _ in range(m)) for _ in range(n))
    return (means[int(0.025 * n)], means[int(0.975 * n)])


def paired_test(d, n=N_BOOT):
    """Paired bootstrap on differences d_i = P3 - P2. Returns (mean, lo, hi, p)."""
    rng = random.Random(SEED)
    m = len(d)
    means = [st.mean(d[rng.randrange(m)] for _ in range(m)) for _ in range(n)]
    means.sort()
    frac_le0 = sum(1 for x in means if x <= 0) / n
    p = 2 * min(frac_le0, 1 - frac_le0)
    return st.mean(d), means[int(0.025 * n)], means[int(0.975 * n)], p


def msd(vals):
    vals = [v for v in vals if v == v]
    if not vals:
        return (float("nan"), float("nan"))
    return (st.mean(vals), st.stdev(vals) if len(vals) > 1 else 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "thesis" / "results" / "10k"))
    ap.add_argument("--corpus", default=str(BACKEND / "data" / "suppliers_synthetic_10k.json"))
    ap.add_argument("--benchmark", default=str(ROOT / "thesis" / "benchmark" / "supplierbench25_10k.json"))
    args = ap.parse_args()

    files = sorted(glob.glob(str(Path(args.dir) / "run_*.json")))
    if not files:
        raise SystemExit(f"no runs in {args.dir}")
    runs = [json.loads(Path(f).read_text()) for f in files]
    corpus = {str(s["id"]): s for s in json.loads(Path(args.corpus).read_text())}
    bench = {q["id"]: q for q in json.loads(Path(args.benchmark).read_text())}
    norm = lambda s: "".join(ch for ch in (s or "").lower() if ch.isalnum())
    name_idx = {norm(s["name"]) for s in corpus.values()}

    # Per system: per-query lists (query-level mean across runs) of each metric.
    out = {"runs": [Path(f).name for f in files], "n_runs": len(runs), "systems": {}}
    per_query_p5 = {}  # system -> {qid: mean p@5}  (for the significance test)

    for sysname in SYSTEMS:
        # collect per (qid, run) then average to per-qid
        agg = defaultdict(lambda: defaultdict(list))  # metric -> qid -> [per-run vals]
        tier = {}
        for r in runs:
            for row in r["per_query_metrics"].get(sysname, []):
                qid = row["query_id"]
                q = bench.get(qid, {})
                rel = set(q.get("ground_truth_supplier_ids") or [])
                ret = row.get("retrieved_ids") or []
                tier[qid] = row.get("difficulty")
                agg["p5"][qid].append(row.get("precision_at_5", 0.0))
                agg["mrr"][qid].append(row.get("reciprocal_rank", 0.0))
                agg["csr"][qid].append(row.get("constraint_satisfaction_rate", 0.0))
                agg["answer"][qid].append(1.0 if ret else 0.0)
                agg["recall5"][qid].append(recall_at_k(ret, rel, 5))
                agg["recall10"][qid].append(recall_at_k(ret, rel, 10))
                agg["ndcg5"][qid].append(ndcg_at_k(ret, rel, 5))
                agg["map5"][qid].append(ap_at_k(ret, rel, 5))
                agg["succ1"][qid].append(success_at_1(ret, rel))
                if row.get("cost_usd") is not None:
                    agg["cost"][qid].append(row["cost_usd"])
                agg["lat"][qid].append(float(row.get("execution_time_ms", 0)))
                # harmonized CSR: re-score this system's picks with the profile scorer
                recs = [corpus[i] for i in ret if i in corpus]
                agg["hcsr"][qid].append(csr_profile(recs, convert_constraints(q.get("constraints", {}))))

        # query-level means
        qmean = {m: {qid: st.mean(v) for qid, v in d.items()} for m, d in agg.items()}
        per_query_p5[sysname] = qmean.get("p5", {})

        sysout = {}
        for m in ["p5", "mrr", "csr", "hcsr", "answer", "recall5", "recall10", "ndcg5", "map5", "succ1", "cost"]:
            if not qmean.get(m):
                continue
            vals = list(qmean[m].values())
            mean, sd = msd(vals)
            entry = {"mean": round(mean, 4), "sd": round(sd, 4)}
            if m in ("p5", "mrr", "csr", "hcsr"):
                lo, hi = bootstrap_ci(vals)
                entry["ci95"] = [round(lo, 4), round(hi, 4)]
            sysout[m] = entry
        # latency: raw mean + pacing-minimized (per-query min across runs)
        raw_lat = [st.mean(v) for v in agg["lat"].values()]
        min_lat = [min(v) for v in agg["lat"].values()]
        sysout["latency_ms_raw"] = round(st.mean(raw_lat), 0) if raw_lat else None
        sysout["latency_ms_pacing_min"] = round(st.mean(min_lat), 0) if min_lat else None
        # cost-per-correct = cost per query / (P@5 * 5)  → $ per correct supplier in top-5
        if sysout.get("cost") and sysout["p5"]["mean"] > 0:
            sysout["cost_per_correct"] = round(sysout["cost"]["mean"] / (sysout["p5"]["mean"] * 5), 6)
        # per-tier P@5
        by_tier = defaultdict(list)
        for qid, v in qmean["p5"].items():
            by_tier[tier.get(qid, "?")].append(v)
        sysout["p5_by_tier"] = {t: round(st.mean(by_tier[t]), 4) for t in ("simple", "medium", "hard") if by_tier.get(t)}
        out["systems"][sysname] = sysout

    # ── P3 gate accuracy + ask-rate; P1 hallucination (pooled over runs) ──
    gate = defaultdict(lambda: [0, 0])
    tp = fp = fn = 0
    asked = defaultdict(int); qtot = defaultdict(int)
    for r in runs:
        for row in r["per_query_metrics"].get("suppliermind", []):
            c = bench.get(row["query_id"], {}).get("constraints", {})
            qtot[row.get("difficulty")] += 1
            if row.get("would_clarify"):
                asked[row.get("difficulty")] += 1
            for sup in (row.get("compliance_data") or []):
                rec = corpus.get(str(sup["supplier_id"]))
                if not rec:
                    continue
                for chk in sup.get("compliance_results", []):
                    tv = true_verdict(chk["constraint_name"], rec, c)
                    if tv is None:
                        continue
                    pred = chk["status"] == "PASS"
                    gate["all"][1] += 1
                    gate["all"][0] += int(pred == tv)
                    if pred and tv: tp += 1
                    elif pred and not tv: fp += 1
                    elif (not pred) and tv: fn += 1
    total_q = sum(qtot.values())
    out["p3_gate_accuracy"] = round(gate["all"][0] / gate["all"][1], 4) if gate["all"][1] else None
    out["p3_gate_pass_precision"] = round(tp / (tp + fp), 4) if (tp + fp) else None
    out["p3_gate_pass_recall"] = round(tp / (tp + fn), 4) if (tp + fn) else None
    out["p3_ask_rate"] = round(sum(asked.values()) / total_q, 4) if total_q else None
    out["p3_ask_rate_by_tier"] = {t: f"{asked[t]}/{qtot[t]}" for t in ("simple", "medium", "hard") if qtot.get(t)}

    hall_total = hall_bad = 0
    for r in runs:
        for row in r["per_query_metrics"].get("p1_singleprompt", []):
            for nm in (row.get("raw_names") or []):
                hall_total += 1
                if norm(nm) not in name_idx:
                    hall_bad += 1
    out["p1_entity_hallucination"] = round(hall_bad / hall_total, 4) if hall_total else None

    # ── paired significance: P3 vs P2 on P@5 (query-level means) ──────────
    common = sorted(set(per_query_p5["suppliermind"]) & set(per_query_p5["p2_rag"]))
    d = [per_query_p5["suppliermind"][q] - per_query_p5["p2_rag"][q] for q in common]
    mean_d, lo, hi, p = paired_test(d)
    out["sig_p3_vs_p2_p5"] = {
        "n_queries": len(common), "mean_diff": round(mean_d, 4),
        "ci95": [round(lo, 4), round(hi, 4)], "bootstrap_p": round(p, 4),
    }

    outfile = Path(args.dir) / "METRICS.json"
    outfile.write_text(json.dumps(out, indent=2))
    _print_md(out)
    print(f"\nwrote {outfile}")


def _print_md(o):
    def row(sysname, m, pct=True):
        e = o["systems"].get(sysname, {}).get(m)
        if not e:
            return "—"
        s = f"{e['mean']:.3f} ± {e['sd']:.3f}"
        if "ci95" in e:
            s += f" [{e['ci95'][0]:.3f}, {e['ci95'][1]:.3f}]"
        return s

    print(f"\n{'='*70}\nSupplierBench-25 on 10k — {o['n_runs']} runs\n{'='*70}")
    print(f"\n{'metric':<16}{'P3 SupplierMind':<30}{'P2 RAG':<24}{'P1':<8}")
    print("-" * 78)
    names = [("p5", "P@5"), ("mrr", "MRR"), ("recall5", "Recall@5"), ("ndcg5", "nDCG@5"),
             ("map5", "MAP@5"), ("succ1", "Success@1"), ("csr", "CSR"), ("hcsr", "CSR-harmonized"),
             ("answer", "answer-rate")]
    for key, lab in names:
        print(f"{lab:<16}{row('suppliermind', key):<30}{row('p2_rag', key):<24}{row('p1_singleprompt', key):<8}")
    print()
    for s in SYSTEMS:
        so = o["systems"][s]
        print(f"{LABELS[s]}: cost/q ${so.get('cost',{}).get('mean',0):.5f}"
              f"  cost/correct ${so.get('cost_per_correct','—')}"
              f"  latency raw {so.get('latency_ms_raw')}ms / pacing-min {so.get('latency_ms_pacing_min')}ms"
              f"  P@5 by tier {so.get('p5_by_tier')}")
    print(f"\nP3 gate accuracy: {o['p3_gate_accuracy']} (PASS precision {o['p3_gate_pass_precision']}, recall {o['p3_gate_pass_recall']})")
    print(f"P3 ask-rate: {o['p3_ask_rate']}  by tier {o['p3_ask_rate_by_tier']}")
    print(f"P1 entity-hallucination: {o['p1_entity_hallucination']}")
    sg = o["sig_p3_vs_p2_p5"]
    print(f"\nP3 vs P2 on P@5 (paired, n={sg['n_queries']}): mean diff {sg['mean_diff']:+.3f} "
          f"CI95 [{sg['ci95'][0]:.3f}, {sg['ci95'][1]:.3f}], bootstrap p={sg['bootstrap_p']:.4f} "
          f"→ {'SIGNIFICANT' if sg['ci95'][0] > 0 else 'not significant'} at 95%")


if __name__ == "__main__":
    main()
