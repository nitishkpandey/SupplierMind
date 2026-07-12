# Benchmark run 2026-07-10T21:18:34.916355+00:00

Corpus: frozen curated-100 supplier corpus (approved + active rows only; pending-review and quarantined rows excluded).
Provider: OpenAI gpt-4o-mini only; no runtime fallback.
Clarification policy: in non-interactive batch mode, a SupplierMind clarification request is scored as an empty returned set.

| Paradigm | Tier | n | P@5 | MRR | CSR | Latency ms | Cost USD |
|----------|------|---|-----|-----|-----|-----------|----------|
| P1 single-prompt | simple | 8 | 0.000 | 0.000 | 0.000 | 3359 | 0.00015 |
| P1 single-prompt | medium | 10 | 0.000 | 0.000 | 0.000 | 3500 | 0.00017 |
| P1 single-prompt | hard | 7 | 0.000 | 0.000 | 0.000 | 3942 | 0.00019 |
| P1 single-prompt | all | 25 | 0.000 | 0.000 | 0.000 | 3579 | 0.00017 |
| P2 RAG | simple | 8 | 0.625 | 0.938 | 0.975 | 6619 | 0.00022 |
| P2 RAG | medium | 10 | 0.380 | 0.850 | 0.758 | 2866 | 0.00022 |
| P2 RAG | hard | 7 | 0.000 | 0.000 | 0.588 | 3306 | 0.00025 |
| P2 RAG | all | 25 | 0.352 | 0.640 | 0.780 | 4190 | 0.00023 |
| P3 SupplierMind | simple | 8 | 0.000 | 0.000 | 0.075 | 14529 | 0.00127 |
| P3 SupplierMind | medium | 10 | 0.320 | 0.800 | 0.656 | 40501 | 0.00195 |
| P3 SupplierMind | hard | 7 | 0.000 | 0.000 | 0.639 | 37550 | 0.00232 |
| P3 SupplierMind | all | 25 | 0.128 | 0.320 | 0.465 | 31364 | 0.00184 |
