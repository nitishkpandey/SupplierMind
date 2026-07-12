# SupplierBench-25 Three-Paradigm Findings

Run date: 2026-07-10  
Benchmark command: `uv run python scripts/run_evaluation.py --p1 --p2 --p3`  
Run commit before benchmark: `82295fce5a136bd74f9ea97579e446f7dd90cb4e`  
Run log: `results/full_benchmark_20260710.log`  
Archived metrics: `results/run_20260710/evaluation_results.json`

## Experimental Setup

- Query set: 25 SupplierBench queries.
- Paradigms: P1 single-prompt LLM, P2 minimal RAG, P3 SupplierMind agentic pipeline.
- Corpus: frozen curated-100 supplier corpus.
- Database filter: approved + active suppliers only.
- Pending-review and quarantined rows were excluded.
- Ground-truth coverage: all 37 unique ground-truth supplier IDs were present as approved + active before the run.
- Milvus vector count before the run: 100.
- Clarification scoring policy: in non-interactive batch mode, a SupplierMind clarification/early-stop branch is scored as an empty returned set.

## Headline Metrics

| Paradigm | P@5 | MRR | CSR | Mean Latency |
|---|---:|---:|---:|---:|
| P1 single-prompt | 0.000 | 0.000 | 0.000 | 3.6s |
| P2 RAG | 0.352 | 0.640 | 0.780 | 4.2s |
| P3 SupplierMind | 0.128 | 0.320 | 0.465 | 31.4s |

## 95% Bootstrap Confidence Intervals

| Paradigm | P@5 CI | MRR CI | CSR CI |
|---|---:|---:|---:|
| P1 single-prompt | 0.000-0.000 | 0.000-0.000 | 0.000-0.000 |
| P2 RAG | 0.224-0.480 | 0.460-0.820 | 0.673-0.877 |
| P3 SupplierMind | 0.048-0.232 | 0.120-0.520 | 0.331-0.593 |

## Tier Breakdown

| Tier | P1 P@5 | P2 P@5 | P3 P@5 | P1 CSR | P2 CSR | P3 CSR |
|---|---:|---:|---:|---:|---:|---:|
| Simple | 0.000 | 0.625 | 0.000 | 0.000 | 0.975 | 0.075 |
| Medium | 0.000 | 0.380 | 0.320 | 0.000 | 0.758 | 0.656 |
| Hard | 0.000 | 0.000 | 0.000 | 0.000 | 0.588 | 0.639 |

## Harmonized CSR

P3's default CSR is computed from its compliance-agent verdicts. The harmonized CSR re-scores P3's returned suppliers with the same profile-based scorer used for P1/P2.

| Scope | P3 Self-Assessed CSR | P3 Harmonized CSR |
|---|---:|---:|
| All | 0.465 | 0.402 |
| Simple | 0.075 | 0.000 |
| Medium | 0.656 | 0.761 |
| Hard | 0.639 | 0.350 |

## Behavioral Findings

- P1 returned zero corpus-resolved suppliers on all 25 queries. This is expected for the no-retrieval/no-tools baseline: it can generate plausible supplier names, but they do not map to the benchmark corpus.
- P2 returned suppliers for all 25 queries and achieved the strongest P@5, MRR, and CSR in this run. Its weakness is not retrieval performance here, but auditability: it has corpus grounding but no per-constraint evidence trail.
- P3 returned suppliers on 11/25 queries and returned no suppliers on 14/25 queries.
- P3 had 8 clarification or early-stop cases with no compliance evidence. These were scored as empty results under the locked batch-mode policy.
- P3 had 6 zero-result cases after compliance evidence was gathered. These are strict gate failures: partial evidence existed, but no supplier survived ranking.
- P3 had 5 parser fallback events and 5 parser parse-failure events in the run log. Several hard/constraint-heavy queries produced polluted product strings, which hurt downstream retrieval.
- P3 used stricter compliance/ranking than P2. This reduced false positives but also reduced P@5 when the corpus contained near-matches rather than full verified matches.
- Hard-tier P@5 was 0 for all paradigms. The sanity check confirms 7/7 hard queries have empty ground truth, so P@5/MRR are 0 by construction there; CSR remains useful for partial constraint satisfaction analysis.
- Runtime was dominated by embedding provider throttling: 51 Voyage retries, 0 OpenAI retries, and 0 LLM fallback events.
- Total recorded LLM spend was USD 0.0559.

## Thesis Interpretation

The run does not support the claim that the agentic system is the highest-precision retrieval system under the current benchmark and corpus. It supports a more nuanced claim:

P2 is the strongest retrieval baseline on this frozen corpus, while P3 is the most auditable and operationally realistic system. P3 provides clarification behavior, deterministic compliance checks, evidence-gated ranking, retry/relaxation behavior, and audit trails, but these same controls reduce recall and expose parser brittleness on constraint-heavy procurement language.

That is a defensible thesis result: agentic architecture improves process transparency and procurement governance, but it does not automatically dominate simpler RAG on retrieval metrics without further parser and calibration work.
