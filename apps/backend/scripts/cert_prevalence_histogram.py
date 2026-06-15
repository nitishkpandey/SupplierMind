"""Cert-prevalence diagnostic: 100-curated vs 10K-synthetic corpus.

Development Plan Phase 0 item. Compares how often each certification appears
in the two corpora. Motivates the CSR-at-scale defence: if the synthetic
corpus carries systematically higher cert prevalence, CSR numbers measured
on it are inflated relative to the curated set.

Outputs (under results/diagnostics/):
  - cert_prevalence.png   grouped horizontal bar chart, prevalence per corpus
  - cert_prevalence.csv   underlying numbers (count + share per corpus)

Run from backend/ with:  uv run python scripts/cert_prevalence_histogram.py
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

BACKEND = Path(__file__).resolve().parents[1]
OUT_DIR = BACKEND.parent / "results" / "diagnostics"

CURATED = BACKEND / "data" / "suppliers_synthetic.json"
SYNTH_10K = BACKEND / "data" / "suppliers_synthetic_10k.json"


def load_certs(path: Path) -> tuple[int, Counter]:
    suppliers = json.loads(path.read_text(encoding="utf-8"))
    counter: Counter = Counter()
    for s in suppliers:
        for cert in set(s.get("certifications") or []):
            counter[cert.strip()] += 1
    return len(suppliers), counter


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n_cur, certs_cur = load_certs(CURATED)
    n_10k, certs_10k = load_certs(SYNTH_10K)

    all_certs = sorted(
        set(certs_cur) | set(certs_10k),
        key=lambda c: -(certs_10k.get(c, 0) / n_10k),
    )

    rows = []
    for cert in all_certs:
        rows.append({
            "certification": cert,
            "curated_count": certs_cur.get(cert, 0),
            "curated_share": round(certs_cur.get(cert, 0) / n_cur, 4),
            "synthetic10k_count": certs_10k.get(cert, 0),
            "synthetic10k_share": round(certs_10k.get(cert, 0) / n_10k, 4),
        })

    csv_path = OUT_DIR / "cert_prevalence.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # Plot
    labels = [r["certification"] for r in rows]
    cur_shares = [r["curated_share"] * 100 for r in rows]
    syn_shares = [r["synthetic10k_share"] * 100 for r in rows]
    y = range(len(labels))
    height = 0.38

    fig, ax = plt.subplots(figsize=(9, max(5, 0.35 * len(labels))))
    ax.barh([i + height / 2 for i in y], cur_shares, height,
            label=f"Curated (n={n_cur})", color="#4C72B0")
    ax.barh([i - height / 2 for i in y], syn_shares, height,
            label=f"Synthetic 10K (n={n_10k})", color="#DD8452")
    ax.set_yticks(list(y), labels)
    ax.invert_yaxis()
    ax.set_xlabel("Share of suppliers holding the certification (%)")
    ax.set_title("Certification prevalence: curated 100 vs synthetic 10K")
    ax.legend()
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    png_path = OUT_DIR / "cert_prevalence.png"
    fig.savefig(png_path, dpi=150)

    print(f"suppliers: curated={n_cur}, synthetic_10k={n_10k}")
    print(f"distinct certs: curated={len(certs_cur)}, synthetic_10k={len(certs_10k)}")
    print(f"wrote {csv_path}")
    print(f"wrote {png_path}")
    # Quick textual summary for the defence writeup
    print("\ncert                          curated%   10k%")
    for r in rows:
        print(f"{r['certification']:<28} {r['curated_share']*100:7.1f} {r['synthetic10k_share']*100:7.1f}")


if __name__ == "__main__":
    main()
