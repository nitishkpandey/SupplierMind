# Benchmark run 2026-06-14T21:04:57.065045+00:00

Corpus: live pool (10,136 suppliers in Postgres / 10,127 in Milvus).
Provider: openai gpt-4o-mini primary, groq fallback armed.

| Paradigm | Tier | n | P@5 | MRR | CSR | Latency ms | Cost USD |
|----------|------|---|-----|-----|-----|-----------|----------|
| P1 single-prompt | simple | 8 | 0.000 | 0.000 | 0.000 | 5606 | 0.00015 |
| P1 single-prompt | medium | 10 | 0.000 | 0.000 | 0.000 | 6263 | 0.00017 |
| P1 single-prompt | hard | 7 | 0.000 | 0.000 | 0.000 | 4977 | 0.00018 |
| P1 single-prompt | all | 25 | 0.000 | 0.000 | 0.000 | 5693 | 0.00017 |
| P2 RAG | simple | 8 | 0.050 | 0.150 | 1.000 | 5048 | 0.00029 |
| P2 RAG | medium | 10 | 0.100 | 0.217 | 0.812 | 3877 | 0.00028 |
| P2 RAG | hard | 7 | 0.000 | 0.000 | 0.492 | 3117 | 0.00027 |
| P2 RAG | all | 25 | 0.056 | 0.135 | 0.783 | 4039 | 0.00028 |
| P3 SupplierMind | simple | 8 | 0.000 | 0.000 | 0.536 | 43293 | 0.00243 |
| P3 SupplierMind | medium | 10 | 0.160 | 0.345 | 0.826 | 42503 | 0.00222 |
| P3 SupplierMind | hard | 7 | 0.000 | 0.000 | 0.593 | 35548 | 0.00194 |
| P3 SupplierMind | all | 25 | 0.064 | 0.138 | 0.668 | 40809 | 0.00220 |
