# SupplierBench-25

SupplierBench-25 is the procurement supplier-discovery benchmark used to compare
the three paradigms in this project (single-prompt LLM, RAG, agentic).

It contains 25 queries with embedded ground-truth supplier IDs, partitioned as
8 simple, 10 medium, and 7 hard.

## Where the files live

- Queries and ground truth: `apps/backend/data/queries_benchmark.json`
- Corpus (10k synthetic suppliers, seed 42): `apps/backend/data/suppliers_synthetic_10k.json`
- Generator: `apps/backend/data/generate_dataset.py`
- Scoring code: `apps/backend/app/evaluation/`
- Harness scripts: `apps/backend/scripts/sanity_check_benchmark.py`, `apps/backend/scripts/smoke_benchmark.py`

## Reproduction

See `BENCHMARK.md` at the repo root for the canonical reproduction procedure
and `scripts/reproduce_benchmark.ps1` for the runner.

## Results

Locked benchmark runs are in `results/` at the repo root, with v2 tagged as
`benchmark-final-v2`.
</content>
