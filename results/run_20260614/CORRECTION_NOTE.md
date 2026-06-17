# Measurement Correction Note

This run was conducted against a regenerated corpus whose uuid4 supplier IDs did not match the ground truth supplier IDs in queries_benchmark.json. As a result:

- **CSR values are valid.** CSR measures constraint satisfaction by supplier attributes, not by ID matching.
- **P@5 and MRR values are NOT valid.** They depend on retrieved-supplier-ID matching against ground-truth IDs, which broke silently because the corpus IDs had been regenerated.

For the canonical reproducible benchmark, see results/run_20260616/ which was run against the committed frozen corpus where supplier IDs match the ground truth.

Phase H Part 3 verification confirmed this on 2026-06-16. Full comparison report: Documents/reference/phase_h_part3_comparison.md (gitignored local file).
