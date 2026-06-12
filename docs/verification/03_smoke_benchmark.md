# Verification 03: Smoke Benchmark (3 queries x 3 paradigms)

**Date:** 2026-06-12T22:30:07.975874+00:00
**Provider:** openai / gpt-4o-mini (groq fallback armed)
**Wall time:** 111s

| Q | Tier | Paradigm | Returned IDs (count) | P@5 | Latency ms | Cost USD |
|---|------|----------|----------------------|-----|-----------|----------|
| 1 | simple | p1_singleprompt | (none) (0) | 0.00 | 5702 | 0.000149 |
| 1 | simple | p2_rag | 9f19a23a, 4511b929, 2bdd0490, 44a3c14d, 2cb1fd18 (5) | 0.20 | 5165 | 0.000316 |
| 1 | simple | p3_suppliermind | 2cb1fd18, 95d0783f, 00d4ed18, e97f9c42, 097e20c2 (5) | 0.00 | 16222 | 0.001825 |
| 10 | medium | p1_singleprompt | (none) (0) | 0.00 | 3932 | 0.000214 |
| 10 | medium | p2_rag | e25b4d53, 11eebd7b, 54e6a6d1, fd2336f4 (4) | 0.00 | 3973 | 0.000274 |
| 10 | medium | p3_suppliermind | 4b6cd4e8, e25b4d53, e26fbbf0, 0400e249, 6d37a680 (5) | 0.20 | 41770 | 0.001647 |
| 23 | hard | p1_singleprompt | (none) (0) | 0.00 | 4757 | 0.000178 |
| 23 | hard | p2_rag | 634d2152, f3dcd91d, 60aba42b, 1b9ece19, baec5a46 (5) | 0.00 | 8142 | 0.000289 |
| 23 | hard | p3_suppliermind | 1b9ece19, 60aba42b, f3dcd91d, baec5a46, a1aec478 (5) | 0.00 | 17746 | 0.001776 |

## Sanity checks
- Cells populated: 9/9 PASS
- Crashes: 0 PASS
- Per-paradigm costs sum to total: PASS

## Cost
- Smoke run total: $0.0067
  - p1_singleprompt: $0.0005
  - p2_rag: $0.0009
  - p3_suppliermind: $0.0052
- Projected full 25-query run (linear): **$0.0556**

Note: paradigm errors (if any) are recorded per row; an error row with an empty ID list still counts as populated output for the gate.
