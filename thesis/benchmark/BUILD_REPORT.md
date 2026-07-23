# SupplierBench 10k — Build Report

Corpus: `suppliers_synthetic_10k.json` (10000 suppliers). Deterministic build (no LLM). Re-running this script reproduces the same file.

Floor: every satisfiable query must have >= 3 matches. Tuning targets per tier: {'simple': 12, 'medium': 8, 'hard': 5}.

Ground truth stores the FULL relevant set (not truncated to 5), so recall is well defined.

## SupplierBench-25 (satisfiable)
| Q | tier | GT | status | tuned | notes |
|---|---|---|---|---|---|
| 1 | simple | 106 | OK | cap=- lead=- certs=- | - |
| 2 | simple | 507 | OK | cap=- lead=- certs=['ISO 9001'] | - |
| 3 | simple | 29 | OK | cap=- lead=- certs=- | - |
| 4 | simple | 25 | OK | cap=- lead=- certs=- | - |
| 5 | simple | 295 | OK | cap=- lead=- certs=['ISO 14001'] | - |
| 6 | simple | 252 | OK | cap=- lead=- certs=['REACH'] | - |
| 7 | simple | 81 | OK | cap=- lead=- certs=- | - |
| 8 | simple | 101 | OK | cap=- lead=- certs=['ISO 22000'] | - |
| 9 | medium | 6 | OK | cap=10000 lead=- certs=['ISO 9001'] | - |
| 10 | medium | 4 | OK | cap=- lead=14 certs=['ISO 9001'] | - |
| 11 | medium | 8 | OK | cap=50000 lead=- certs=- | - |
| 12 | medium | 13 | OK | cap=- lead=- certs=['ISO 27001'] | - |
| 13 | medium | 6 | OK | cap=100000 lead=- certs=['REACH'] | - |
| 14 | medium | 6 | OK | cap=100000 lead=- certs=- | - |
| 15 | medium | 5 | OK | cap=- lead=14 certs=['CE'] | - |
| 16 | medium | 35 | OK | cap=- lead=- certs=['ISO 9001'] | - |
| 17 | medium | 8 | OK | cap=200000 lead=- certs=['ISO 22000'] | - |
| 18 | medium | 8 | OK | cap=20000 lead=- certs=['CE'] | - |
| 19 | hard | 5 | OK | cap=50000 lead=- certs=['ISO 9001'] | lead-time cap dropped — no round cap kept >=3 with the other constraints |
| 20 | hard | 5 | OK | cap=100000 lead=60 certs=['ISO 9001'] | - |
| 21 | hard | 4 | OK | cap=- lead=21 certs=['ISO 27001'] | - |
| 22 | hard | 6 | OK | cap=100000 lead=- certs=['REACH'] | lead-time cap dropped — no round cap kept >=3 with the other constraints |
| 23 | hard | 5 | OK | cap=5000 lead=30 certs=['ISO 9001'] | - |
| 24 | hard | 5 | OK | cap=100000 lead=- certs=['ISO 9001'] | lead-time cap dropped — no round cap kept >=3 with the other constraints |
| 25 | hard | 5 | OK | cap=100000 lead=45 certs=- | - |

Floor check: ALL PASS.

## Abstention-5 (must be empty)
| Q | tier | pool | status | query |
|---|---|---|---|---|
| A1 | unsat | 0 | OK(empty) | AS9100 aerospace-certified logistics providers in  |
| A2 | unsat | 0 | OK(empty) | ISO 27001 and IATF 16949 automotive-certified soft |
| A3 | unsat | 0 | OK(empty) | IATF 16949 automotive-certified food ingredient su |
| A4 | unsat | 0 | OK(empty) | ISO 9001 metal suppliers in Germany with capacity  |
| A5 | unsat | 0 | OK(empty) | ISO 14001 certified textile suppliers in Iceland |

Empty check: ALL PASS.

## Reviewer notes
- Capacity units come from the corpus per category (10k uses one unit per category).
- Thresholds are auto-tuned round numbers, not hand-picked. Edit any query in the
  JSON and re-run the diagnostic to re-verify; adjust intents in this script to change wording.
- Geography: 10k is global, so hard queries use country + stacked cert/capacity/lead
  constraints rather than tight km-radius (radius on a sparse global corpus was the main
  cause of the old empty hard tier). Radius-based queries can be added back per-city if you
  want them, as long as the floor still holds.