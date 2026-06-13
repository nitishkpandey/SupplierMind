# Benchmark run 2026-06-13T00:59:55.438051+00:00

Corpus: live pool (10,136 suppliers in Postgres / 10,127 in Milvus).
Provider: openai gpt-4o-mini primary, groq fallback armed.

| Paradigm | Tier | n | P@5 | MRR | CSR | Latency ms | Cost USD |
|----------|------|---|-----|-----|-----|-----------|----------|
| P1 single-prompt | simple | 8 | 0.000 | 0.000 | 0.000 | 4192 | 0.00016 |
| P1 single-prompt | medium | 10 | 0.000 | 0.000 | 0.000 | 5271 | 0.00017 |
| P1 single-prompt | hard | 7 | 0.000 | 0.000 | 0.000 | 4717 | 0.00018 |
| P1 single-prompt | all | 25 | 0.000 | 0.000 | 0.000 | 4771 | 0.00017 |
| P2 RAG | simple | 8 | 0.050 | 0.150 | 1.000 | 5743 | 0.00030 |
| P2 RAG | medium | 10 | 0.100 | 0.217 | 0.812 | 4144 | 0.00028 |
| P2 RAG | hard | 7 | 0.000 | 0.000 | 0.473 | 3328 | 0.00029 |
| P2 RAG | all | 25 | 0.056 | 0.135 | 0.777 | 4427 | 0.00029 |
| P3 SupplierMind | simple | 8 | 0.025 | 0.062 | 0.524 | 39434 | 0.00266 |
| P3 SupplierMind | medium | 10 | 0.160 | 0.328 | 0.831 | 43077 | 0.00214 |
| P3 SupplierMind | hard | 7 | 0.000 | 0.000 | 0.582 | 35619 | 0.00211 |
| P3 SupplierMind | all | 25 | 0.072 | 0.151 | 0.663 | 39823 | 0.00230 |
