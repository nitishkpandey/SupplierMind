# Verification 06: Post-Lock Sanity Checks

**Date:** 2026-07-10T21:20:06.024644+00:00
**Run dir:** /Users/nitishkumarpandey/Desktop/SupplierMind/results/run_20260710
**Run log:** /Users/nitishkumarpandey/Desktop/SupplierMind/results/full_benchmark_20260710.log
**Verdict:** NO BLOCKERS

| Check | Result | Detail |
|-------|--------|--------|
| coverage p1_singleprompt | PASS | 25/25 queries |
| coverage p2_rag | PASS | 25/25 queries |
| coverage suppliermind | PASS | 25/25 queries |
| same query set across paradigms | PASS | identical ordered query_id lists |
| same corpus across paradigms | PASS | single process, single benchmark_file, frozen curated-100 corpus (approved + active rows only; pending-review/quarantined rows excluded) (/Users/nitishkumarpandey/Desktop/SupplierMind/apps/backend/data/queries_benchmark.json); run_id=1b6417b9-15a4-4422-b188-cd4bae6ed038 |
| retry counts | PASS | openai=0, voyage=51, llm-fallback events=0 (fallbacks would mix models across paradigms) |
| warm-up p1_singleprompt | PASS | first=2681ms median=3468ms ratio=0.77 |
| warm-up p2_rag | PASS | first=3508ms median=2892ms ratio=1.21 |
| warm-up suppliermind | PASS | first=10739ms median=29787ms ratio=0.36 |
| cost consistency | PASS | sum(per-query)=0.0559 vs last [llm-cost] running total=0.0559 (dashboard cross-check is manual) |
| ground-truth-zero queries score 0 | PASS | 7/7 hard queries (plus any others) have empty ground truth; all such cells P@5=MRR=0 |

Notes:
- 'Same corpus' holds by construction: all paradigms ran in one process
  against the same approved + active curated supplier corpus in one runner invocation.
- Ground-truth-zero affects 7/7 hard queries and 1 non-hard queries; P@5 and MRR are 0 there
  by construction for every paradigm. CSR still differentiates.
- OpenAI dashboard total is a manual cross-check (no spend API).
