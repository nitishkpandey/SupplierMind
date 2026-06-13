# Verification 06: Post-Lock Sanity Checks

**Date:** 2026-06-13T01:00:06.936726+00:00
**Run dir:** D:\Nitish - Projects\SupplierMind\results\run_20260613
**Run log:** ..\results\full_benchmark_gpt4omini_20260613_clean.err.log
**Verdict:** NO BLOCKERS

| Check | Result | Detail |
|-------|--------|--------|
| coverage p1_singleprompt | PASS | 25/25 queries |
| coverage p2_rag | PASS | 25/25 queries |
| coverage suppliermind | PASS | 25/25 queries |
| same query set across paradigms | PASS | identical ordered query_id lists |
| same corpus across paradigms | PASS | single process, single benchmark_file, one live corpus (D:\Nitish - Projects\SupplierMind\backend\data\queries_benchmark.json); run_id=77e41957-9464-4883-860f-fe76155eed06 |
| retry counts | PASS | openai=0, groq=0, voyage=43, llm-fallback events=0 (fallbacks would mix models across paradigms) |
| warm-up p1_singleprompt | PASS | first=3534ms median=4741ms ratio=0.75 |
| warm-up p2_rag | PASS | first=5027ms median=3975ms ratio=1.26 |
| warm-up suppliermind | PASS | first=59596ms median=41616ms ratio=1.43 |
| cost consistency | PASS | sum(per-query)=0.0689 vs last [llm-cost] running total=0.0689 (dashboard cross-check is manual) |
| ground-truth-zero queries score 0 | PASS | 7/7 hard queries (plus any others) have empty ground truth; all such cells P@5=MRR=0 |

Notes:
- 'Same corpus' holds by construction: all paradigms ran in one process
  against the one live Postgres/Milvus pool in a single runner invocation.
- Ground-truth-zero affects all 7 hard queries and medium Q13; P@5 and MRR
  are 0 there by construction for every paradigm. CSR still differentiates.
- OpenAI dashboard total is a manual cross-check (no spend API).
