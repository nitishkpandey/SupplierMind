# Thesis Reproducibility Package

This directory contains the public evidence package for the SupplierMind master's thesis. It reproduces the reported SupplierBench-24 analysis from sanitized archived runs without calling an LLM, connecting to a database, or using API credentials.

## Reproduce the results

From the repository root:

```bash
cd apps/backend
uv sync --group dev
uv run python ../../thesis/scripts/reproduce.py
```

The command regenerates the metrics, diagnostics, ablation summary, abstention summary, and six Chapter 5 figures. It then verifies benchmark integrity, archive sanitization, expected headline metrics, and every checksum recorded in `PROVENANCE.json`.

Expected headline values:

| System | Precision@5 overall | Simple | Medium | Hard |
|---|---:|---:|---:|---:|
| P3 SupplierMind | 0.747 | 0.950 | 0.664 | 0.613 |
| P2 semantic RAG | 0.517 | 0.950 | 0.340 | 0.233 |
| P1 single prompt control | 0.000 | 0.000 | 0.000 | 0.000 |

The paired P3 minus P2 difference is `+0.230` across 24 query-level means, with a 95 percent bootstrap interval of `[0.123, 0.337]` and `p < 0.001`.

## Why the benchmark contains 24 queries

The original archived benchmark contained 25 rows. Original Query 22 was character-for-character identical to Query 13 but carried a different difficulty label. Keeping both would give one query intent twice the weight and weaken the independence of the query-level analysis.

The published analysis therefore removes original Query 22 and recomputes all dependent statistics offline over the 24 unique queries. The exclusion is methodological, not performance driven. The original run files remain recoverable at source commit `9820863add00c82515d53b3537a562a707123913`; `EXCLUSION.json` records the exact identifier, duplicate relationship, renumbering, and archive inventory.

## Package contents

```text
thesis/
├── benchmark/       SupplierBench-24 and Abstention-5 definitions
├── figures/         Deterministically regenerated Chapter 5 figures
├── results/         Sanitized runs and regenerated analysis outputs
├── scripts/         Offline preparation, analysis, figure, and verification tools
├── tests/           Package integrity and reproduction tests
├── EXCLUSION.json   Duplicate-query exclusion record
└── PROVENANCE.json  Source commits, model identifiers, sizes, and SHA256 checksums
```

The tracked 10,000-supplier corpus remains at `apps/backend/data/suppliers_synthetic_10k.json` because the metric scripts use it for harmonized constraint scoring.

## Reproduction versus rerunning

The command above reproduces the published analysis from archived observations. It does not claim to recreate stochastic model responses.

A live rerun requires the historical experimental implementation, PostgreSQL, Milvus, Redis, valid OpenAI and Voyage credentials, and paid model calls. It can produce different values because language model generation and service behavior are not deterministic. For that reason, live reruns are not part of the default public verification path.

## Interpretation limits

1. P1 is a negative control because synthetic supplier names are unavailable to a model using parametric knowledge alone.
2. P2 and P3 share the embedding model and vector index, but P3 additionally applies structured retrieval and compliance-aware ranking.
3. The difficulty tiers combine the number and selectivity of constraints. The hard tier is not a pure controlled manipulation of constraint count, so H1 is reported as partially supported.
4. Verified Precision@5 evaluates whether relevant recommendations also pass the system's evidence gate. It is a governance-oriented usability metric rather than a neutral ranking metric.
5. Abstention-5 contains five queries and one archived run, so its result is indicative rather than confirmatory.
