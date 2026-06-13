# Verification 04: Full Three-Paradigm Benchmark (GPT-4o-mini)

**Date:** 2026-06-13
**Run id:** 77e41957-9464-4883-860f-fe76155eed06
**Run dir:** `results/run_20260613/`
**Logs:** `results/full_benchmark_gpt4omini_20260613_clean.log` / `.err.log`
**Provider:** OpenAI gpt-4o-mini, 311/311 LLM calls (zero Groq fallbacks, zero OpenAI retries)
**Corpus:** live pool, 10,136 suppliers in Postgres / 10,127 in Milvus, seed 42
**Queries:** SupplierBench-25 (25/25 completed, zero per-query errors)
**Total LLM spend:** $0.0689 (matches sum of per-query costs exactly)
**Wall time:** ~23 min (02:36–02:59 local)

## Headline metrics, per paradigm per tier

| Paradigm | Tier | n | P@5 | MRR | CSR | Latency ms | Cost USD |
|----------|------|---|-----|-----|-----|-----------|----------|
| P1 single-prompt | simple | 8 | 0.000 | 0.000 | 0.000 | 4192 | 0.00016 |
| P1 single-prompt | medium | 10 | 0.000 | 0.000 | 0.000 | 5271 | 0.00017 |
| P1 single-prompt | hard | 7 | 0.000 | 0.000 | 0.000 | 4717 | 0.00018 |
| P1 single-prompt | all | 25 | 0.000 | 0.000 | 0.000 | 4771 | 0.00017 |
| P2 RAG | simple | 8 | 0.050 | 0.150 | 1.000 | 5743 | 0.00030 |
| P2 RAG | medium | 10 | 0.100 | 0.217 | 0.812 | 4144 | 0.00028 |
| P2 RAG | hard | 7 | 0.000 | 0.000 | 0.473 | 3328 | 0.00029 |
| P2 RAG | all | 25 | 0.056 | 0.135 | 0.777 | 4427 | 0.00029 |
| P3 SupplierMind | simple | 8 | 0.025 | 0.062 | 0.524 | 39434 | 0.00266 |
| P3 SupplierMind | medium | 10 | 0.160 | 0.328 | 0.831 | 43077 | 0.00214 |
| P3 SupplierMind | hard | 7 | 0.000 | 0.000 | 0.582 | 35619 | 0.00211 |
| P3 SupplierMind | all | 25 | 0.072 | 0.151 | 0.663 | 39823 | 0.00230 |

Reference baselines from the same run (not LLM paradigms): keyword SQL
P@5=0.000 / CSR=0.268; manual simulation P@5=0.024 / CSR=0.680.

## Bootstrap 95% CIs (1,000 resamples, seed 42)

| Paradigm | P@5 | MRR | CSR |
|----------|-----|-----|-----|
| P1 single-prompt | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| P2 RAG | 0.056 [0.016, 0.104] | 0.135 [0.037, 0.263] | 0.777 [0.676, 0.872] |
| P3 SupplierMind | 0.072 [0.024, 0.120] | 0.151 [0.053, 0.278] | 0.663 [0.547, 0.781] |

## CSR harmonization (post-lock inspection correction)

Inspection before tagging found the published P3 CSR is **not comparable** to
P1/P2: the runner scores P3 from the compliance agent's own verdicts
(`constraint_satisfaction_rate_from_compliance`), and on 6 of 25 queries the
agent checked certifications it inferred itself but the benchmark never asked
for (Q1, Q3, Q4, Q7, Q11, Q14). P1/P2 are scored from supplier profiles
against benchmark constraints. Re-scoring P3's returned suppliers with the
identical profile-based scorer (`scripts/harmonize_csr.py`, no LLM calls, raw
run data untouched → `results/run_20260613/csr_harmonized.json`):

| Scope | CSR self-assessed (original) | CSR harmonized (comparable) |
|-------|------------------------------|------------------------------|
| all | 0.663 | **0.794** |
| simple | 0.524 | 0.875 |
| medium | 0.831 | 0.898 |
| hard | 0.582 | 0.552 |

**With comparable scoring P3 leads P2 on CSR overall (0.794 vs 0.777) and on
every tier except simple** (0.875 vs 1.000, driven by under-returning: Q5
returned zero suppliers). Use the harmonized column for cross-paradigm
comparison; the self-assessed column remains meaningful as the agent's own
evidence-gate strictness measure.

## Evidence-link ratio and auditability

| Paradigm | Evidence-link ratio | Auditability (0–3) |
|----------|--------------------:|-------------------:|
| P1 single-prompt | 0.0 | 0 — parametric names, no corpus link |
| P2 RAG | 1.0 | 1 — corpus-grounded picks, no per-constraint evidence |
| P3 SupplierMind | 1.0 | 3 — per-constraint verdicts with quoted evidence + ReAct trace |

## Plots

`results/run_20260613/plots/`: headline_bars.png, tier_breakdown.png,
latency_boxplot.png, cost_per_query.png.

## Key findings

1. **P1 scores zero on everything — and this is the finding, not a bug.**
   GPT-4o-mini suggests plausible real-world companies (Foxconn,
   ThyssenKrupp, Jabil…) that do not exist in the synthetic corpus, so no
   suggestion ever resolves to a corpus supplier. Evidence-link ratio 0.0.
2. **P3 wins the medium tier decisively** (P@5 0.160 vs 0.100, MRR 0.328 vs
   0.217, CSR 0.831 vs 0.812 over P2) — the tier where multi-constraint
   reasoning matters and ground truth exists.
3. **Hard tier P@5/MRR are 0 for every paradigm by construction** (all 7 hard
   queries have empty ground truth). CSR still differentiates: P3 0.582 >
   P2 0.473.
4. **P3 simple-tier CSR (0.524) is below P2 (1.000)** — flagged for
   inspection before locking; see open questions.
5. **Cost/latency trade-off:** P3 is ~8x P2's cost (0.23¢ vs 0.03¢ per
   query) and ~9x its latency (~40s vs ~4.4s) for the evidence and
   auditability gains.

## Pre-lock inspection results (Step 7 gate)

Three flagged items were inspected before tagging; all resolved.

1. **Q19 vs Q23 refusal inconsistency → consistent threshold behaviour.**
   P3 returns candidates whose verified compliance clears the ranking
   threshold and refuses when none do: Q19's best candidates passed 3/4
   constraints (returned as partial matches, all real corpus suppliers — no
   fabrication), Q23's best passed only 1/3 (refused, empty set). One
   sentence for the viva: refusal is a function of best-candidate compliance,
   not an explicit impossibility detector.
2. **Q5 zero-supplier → one-off clarification request, not a crash and not
   gate over-filtering.** The pipeline ended `needs_clarification` with zero
   results (the single-turn benchmark cannot answer back). A live re-run of
   the identical parser call reproduced `needs_clarification=False`,
   so this is LLM output variance on one query (1/25), an honest cost of
   benchmarking an interactive system single-turn. (Side defect logged: the
   eval harness passes non-UUID query ids, so persisting the pending
   clarification failed — harmless here, `badly formed hexadecimal UUID
   string` in the log.)
3. **Parser over-extraction → systemic on simple/medium (6/25 queries), and
   it contaminated the published CSR — fixed by harmonization (section
   above).** Geo radius is mapped onto the country field on all 6
   geo-constrained hard queries ("required country is Berlin/Bremen…") —
   systematic, affects P3's location verdicts only, direction is
   conservative (penalises P3), future-work item.

Also noted: an earlier same-night run (00:52–02:24) was contaminated by a
stale dead `OPENAI_API_KEY` env var: all 253 calls fell back to Groq
llama-3.1-8b. Archived at `results/groq_contaminated_run_20260613/` — numbers
there are NOT comparable and NOT the canonical run.

## Sanity checks

See `docs/verification/06_sanity_checks.md` — 11/11 PASS, NO BLOCKERS
(coverage, same corpus/query set, zero fallbacks, no warm-up skew, cost
consistency, ground-truth-zero behaviour).

Not yet tagged — awaiting inspection (Step 7: `benchmark-final-v1`).
