# Verification 05: Benchmark Lock (`benchmark-final-v1`)

**Decision:** Path A — lock the 2026-06-13 GPT-4o-mini run as canonical. Known
parser bugs (over-extraction, geo-to-country) are named honestly and deferred
to the production sprint; a v2 re-run happens only with clear gain.

## Locked run

| Field | Value |
|-------|-------|
| Run id | `77e41957-9464-4883-860f-fe76155eed06` |
| Date | 2026-06-13 |
| Wall time | 02:38:05 → 02:58:59 local (~21 min) |
| Provider | OpenAI, 311/311 LLM calls, zero Groq fallbacks, zero OpenAI retries |
| Model | `gpt-4o-mini` alias → resolves to **`gpt-4o-mini-2024-07-18`** (verified against the live API 2026-06-13; sole gpt-4o-mini snapshot OpenAI publishes). Config pinning to the dated snapshot is production-sprint item P-S4. |
| Corpus | live pool, 10,136 in Postgres / 10,127 in Milvus, seed 42 |
| Queries | SupplierBench-25, 25/25 completed, zero per-query errors |
| Total spend | $0.0689 (per-query sum == log running total) |
| Artifacts | `results/run_20260613/` (results, bootstrap CIs, 4 plots, summary table, `csr_harmonized.json`) |
| Sanity | `docs/verification/06_sanity_checks.md` — 11/11 PASS, NO BLOCKERS |

## Headline numbers (all 25 queries)

| Paradigm | P@5 | MRR | CSR (self) | CSR (harmonized) | Latency | Cost/query |
|----------|-----|-----|-----------|------------------|---------|-----------|
| P1 single-prompt | 0.000 | 0.000 | 0.000 | 0.000 | 4.8s | $0.0002 |
| P2 RAG | 0.056 | 0.135 | 0.777 | 0.777 | 4.4s | $0.0003 |
| P3 SupplierMind | 0.072 | 0.151 | 0.663 | **0.794** | 39.8s | $0.0023 |

Harmonized CSR (profile-based scorer, identical to P1/P2) is the comparable
column; P3 leads P2 overall and on every tier except simple. See
`docs/verification/04_full_benchmark.md` for the full per-tier table, CIs,
evidence-link ratio, auditability rubric, and the pre-lock inspection notes.

## Known limitations carried into the lock (defer to sprint / thesis)

1. Parser over-extracts certification constraints on 6/25 queries (Q1, Q3, Q4,
   Q7, Q11, Q14) — inflated the self-assessed CSR; corrected by harmonization.
2. Geo-radius mapped onto the country field on all 6 geo-constrained hard
   queries — conservative (penalises P3 only). Production-sprint fix P-S5.
3. Q5 ended `needs_clarification` with zero results (1/25 LLM variance, not
   reproducible on re-run); harness also logged a non-UUID query-id persist
   error (harmless in eval).
4. Refusal on impossible queries is inconsistent (Q23 empty set, Q19 returned
   5) — a function of best-candidate compliance, not an impossibility detector.

## Provenance note

The pre-lock state is commit `e967687` (HEAD before the lock commit). The lock
commit adds: `results/run_20260613/`, the verification/supervisor docs, the
analysis/sanity/gallery/harmonize scripts, and the runner checkpoint change.
`benchmark-final-v1` is tagged on that lock commit. The original Groq-era
numbers remain at `results/groq_baseline_v0/` (tag `groq-baseline-v0`,
commit 962ba80) — a separate artifact from the Groq-fallback-contaminated run
archived at `results/groq_contaminated_run_20260613/`.

## To execute the lock (your git, per your commit preference)

```bash
# from repo root, on main
git add results/run_20260613 results/groq_contaminated_run_20260613 \
        docs/verification docs/supervisor docs/audits \
        backend/app/evaluation/runner.py \
        backend/scripts/analyze_benchmark.py backend/scripts/sanity_check_benchmark.py \
        backend/scripts/build_output_gallery.py backend/scripts/harmonize_csr.py \
        backend/data/evaluation_results.json backend/data/thesis_report.json \
        backend/data/evaluation_checkpoint.json \
        Documents/SupplierMind_Development_Plan.md
git commit -m "benchmark: lock GPT-4o-mini SupplierBench-25 run (run_20260613)"
git tag -a benchmark-final-v1 -m "Canonical GPT-4o-mini three-paradigm benchmark, 2026-06-13"
git tag --list | grep benchmark-final-v1   # confirm
```

Once tagged, the production sprint proceeds: Groq hard-removal (post-tag, since
the tag must pin the Groq-armed as-run state), model-snapshot pinning (P-S4),
and the read-only code audits.
