# Benchmark run 2026-06-16T10:20:39.728375+00:00

Corpus: live pool (10,136 suppliers in Postgres / 10,127 in Milvus).
Provider: openai gpt-4o-mini primary, groq fallback armed.

| Paradigm | Tier | n | P@5 | MRR | CSR | Latency ms | Cost USD |
|----------|------|---|-----|-----|-----|-----------|----------|
| P1 single-prompt | simple | 8 | 0.000 | 0.000 | 0.000 | 3838 | 0.00016 |
| P1 single-prompt | medium | 10 | 0.000 | 0.000 | 0.000 | 4134 | 0.00017 |
| P1 single-prompt | hard | 7 | 0.000 | 0.000 | 0.000 | 4082 | 0.00019 |
| P1 single-prompt | all | 25 | 0.000 | 0.000 | 0.000 | 4025 | 0.00017 |
| P2 RAG | simple | 8 | 0.625 | 0.938 | 0.975 | 3035 | 0.00021 |
| P2 RAG | medium | 10 | 0.380 | 0.850 | 0.782 | 3045 | 0.00023 |
| P2 RAG | hard | 7 | 0.000 | 0.000 | 0.602 | 4370 | 0.00026 |
| P2 RAG | all | 25 | 0.352 | 0.640 | 0.793 | 3413 | 0.00023 |
| P3 SupplierMind | simple | 8 | 0.525 | 0.792 | 0.650 | 38870 | 0.00125 |
| P3 SupplierMind | medium | 10 | 0.320 | 0.750 | 0.596 | 40057 | 0.00181 |
| P3 SupplierMind | hard | 7 | 0.000 | 0.000 | 0.571 | 37013 | 0.00226 |
| P3 SupplierMind | all | 25 | 0.296 | 0.553 | 0.606 | 38825 | 0.00176 |
