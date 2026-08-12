"""Two additional evaluation metrics for the thesis, computed deterministically from
the committed benchmark runs — NO API keys, NO cost, nothing hard-coded.

  1. Verified Precision@k  — precision that counts a returned supplier only if it is
     both relevant (in the ground truth) AND fully evidence-verified (every constraint
     passed the compliance / quote-or-fail gate). It fuses correctness and
     verifiability into one number, which no standard metric does.

  2. bpref (Buckley & Voorhees, 2004) — a binary-preference metric that scores a
     system on judged documents only, so it does not penalise relevant-but-unjudged
     results. It is reported here for completeness and is the metric intended for the
     future open-web experiment, where relevance judgments become incomplete.

Run:  python thesis/scripts/compute_extra_metrics.py
Writes thesis/results/10k/EXTRA_METRICS.json and prints a summary.
"""
import json
import glob
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = sorted(glob.glob(str(ROOT / "thesis" / "results" / "10k" / "run_*_r*.json")))
CORPUS = ROOT / "apps" / "backend" / "data" / "suppliers_synthetic_10k.json"
OUT = ROOT / "thesis" / "results" / "10k" / "EXTRA_METRICS.json"

CORPUS_SIZE = len(json.loads(CORPUS.read_text()))   # read, do not hard-code


def verified_precision_at_k(rec, k=5):
    """Fraction of the top-k that are BOTH relevant AND fully evidence-verified."""
    gt = set(rec["ground_truth_ids"])
    top = rec["retrieved_ids"][:k]
    verified = {c["supplier_id"]: c.get("overall_pass", False)
                for c in (rec.get("compliance_data") or [])}
    hits = sum(1 for sid in top if sid in gt and verified.get(sid, False))
    return hits / k


def bpref(ranking, rel, corpus_size):
    """Standard trec_eval bpref over a fully-judged corpus."""
    R = len(rel)
    if R == 0:
        return None
    N = corpus_size - R
    if N == 0:
        return 1.0
    denom = min(R, N)
    nonrel_above = 0
    total = 0.0
    for did in ranking:
        if did in rel:
            total += 1.0 - min(nonrel_above, R) / denom
        else:
            nonrel_above += 1
    return total / R


def main():
    result = {"corpus_size": CORPUS_SIZE, "n_runs": len(RUNS), "systems": {}}
    label = {"suppliermind": "P3 SupplierMind", "p2_rag": "P2 RAG",
             "p1_singleprompt": "P1 single-prompt"}
    print(f"\n{'system':18}{'Verified P@5':>14}{'bpref':>10}   bpref by tier")
    print("-" * 70)
    for sys in ("suppliermind", "p2_rag", "p1_singleprompt"):
        vp, bp, bp_tier = [], [], {}
        for f in RUNS:
            pq = json.loads(Path(f).read_text())["per_query_metrics"]
            if sys not in pq or not pq[sys]:
                continue
            for rec in pq[sys]:
                vp.append(verified_precision_at_k(rec))
                b = bpref(rec["retrieved_ids"], set(rec["ground_truth_ids"]), CORPUS_SIZE)
                if b is not None:
                    bp.append(b)
                    bp_tier.setdefault(rec["difficulty"], []).append(b)
        if not vp:
            continue
        vp_mean = statistics.mean(vp)
        bp_mean = statistics.mean(bp)
        tiers = {t: round(statistics.mean(v), 3) for t, v in bp_tier.items()}
        result["systems"][sys] = {
            "verified_precision_at_5": round(vp_mean, 4),
            "bpref": round(bp_mean, 4),
            "bpref_by_tier": tiers,
        }
        print(f"{label[sys]:18}{vp_mean:>14.3f}{bp_mean:>10.3f}   {tiers}")

    OUT.write_text(json.dumps(result, indent=2))
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
