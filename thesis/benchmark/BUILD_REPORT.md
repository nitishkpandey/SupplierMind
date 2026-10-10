# SupplierBench-24 Derivation Report

## Source

- Corpus: `apps/backend/data/suppliers_synthetic_10k.json`
- Corpus size: 10,000 procedurally generated suppliers
- Original benchmark: SupplierBench-25 at commit `9820863add00c82515d53b3537a562a707123913`
- Corrected benchmark: `supplierbench24_10k.json`

## Correction

Original Query 22 was an exact textual duplicate of Query 13. Query 22 was removed before analysis, while Query 13 was retained. Original queries 23 to 25 are renumbered as corrected queries 22 to 24 and retain `source_query_number` for traceability.

No model was called and no result was regenerated during this correction. Every metric was recomputed from the retained archived per-query observations.

## Integrity checks

- 24 unique query identifiers
- 24 unique normalized query texts
- Sequential corrected query numbers from 1 to 24
- At least three ground truth suppliers for every satisfiable query
- Five Abstention-5 queries with zero ground truth suppliers
- Five main runs, three no-compliance ablation runs, and one abstention run
- Free text reasoning removed from every public archive
- No email address, external URL, or key-shaped secret in the public archives

Run `python thesis/scripts/verify_reproduction.py` from the repository root to repeat these checks.
