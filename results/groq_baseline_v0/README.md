# Groq-era benchmark baseline (v0)

Snapshot taken 2026-06-11 (Development Plan, Phase 0) before the OpenAI
provider migration re-runs. These are the canonical Groq-era numbers
(llama-3.1-8b-instant via Groq free tier); after the GPT-4o-mini benchmark
lands these move to the thesis appendix.

Contents:

- `evaluation_results.json` / `queries_benchmark.json`: live copies from
  `backend/data/` at snapshot time.
- `baseline_100_evaluation_results.json`: Week-2 100-supplier baseline run.
- `week1_supplierbench/`: full Week-1 SupplierBench-25 archive, including the
  429-storm first run (tpm=14400 misconfig), the clean canonical run, logs,
  thesis report JSONs and the LaTeX results table. Canonical Week-1 numbers:
  SupplierMind P@5=0.336, CSR=0.686, MRR=0.640 (approved_only, clean run).
- `week2_supplierbench_10k/`: Week-2 re-run against the 10K synthetic corpus.

Source folders (unchanged): `Documents/thesis_evidence/week_1_speed_and_trust/supplierbench/`
and `Documents/thesis_evidence/week_2_production/`.
