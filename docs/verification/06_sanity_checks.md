# Verification 06: Post-Lock Sanity Checks

**Date:** 2026-06-14T21:06:20.642353+00:00
**Run dir:** D:\Nitish - Projects\SupplierMind\results\run_20260614
**Run log:** D:\Nitish - Projects\SupplierMind\results\full_benchmark_20260614.log
**Verdict:** NO BLOCKERS

| Check | Result | Detail |
|-------|--------|--------|
| coverage p1_singleprompt | PASS | 25/25 queries |
| coverage p2_rag | PASS | 25/25 queries |
| coverage suppliermind | PASS | 25/25 queries |
| same query set across paradigms | PASS | identical ordered query_id lists |
| same corpus across paradigms | PASS | single process, single benchmark_file, one live corpus (D:\Nitish - Projects\SupplierMind\backend\data\queries_benchmark.json); run_id=dc96c41c-3ad7-46c3-8362-af52598fdbab |
| retry counts | PASS | openai=0, groq=0, voyage=45, llm-fallback events=0 (fallbacks would mix models across paradigms) |
| warm-up p1_singleprompt | PASS | first=3996ms median=4907ms ratio=0.81 |
| warm-up p2_rag | PASS | first=4529ms median=3945ms ratio=1.15 |
| warm-up suppliermind | PASS | first=37172ms median=42561ms ratio=0.87 |
| cost consistency | PASS | sum(per-query)=0.0663 vs last [llm-cost] running total=0.0663 (dashboard cross-check is manual) |
| ground-truth-zero queries score 0 | PASS | 7/7 hard queries (plus any others) have empty ground truth; all such cells P@5=MRR=0 |

Notes:
- 'Same corpus' holds by construction: all paradigms ran in one process
  against the one live Postgres/Milvus pool in a single runner invocation.
- Ground-truth-zero affects all 7 hard queries and medium Q13; P@5 and MRR
  are 0 there by construction for every paradigm. CSR still differentiates.
- OpenAI dashboard total is a manual cross-check (no spend API).
