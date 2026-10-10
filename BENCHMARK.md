# SupplierBench-24

SupplierBench-24 is the corrected public benchmark used to reproduce the SupplierMind thesis analysis. It evaluates three supplier-discovery paradigms against a frozen, procedurally generated corpus of 10,000 suppliers.

## Scope

| Item | Published configuration |
|---|---|
| Corpus | `apps/backend/data/suppliers_synthetic_10k.json` |
| Satisfiable queries | `thesis/benchmark/supplierbench24_10k.json` |
| Unsatisfiable queries | `thesis/benchmark/abstention5_10k.json` |
| Repeated runs | Five main, three no-compliance ablation, one abstention |
| Primary unit | Query-level mean across repeated runs |
| Primary comparison | P3 SupplierMind versus P2 semantic RAG |
| Language model | `gpt-4o-mini-2024-07-18` |
| Embedding model | `voyage-3-lite` |

The supplier corpus and benchmark contain synthetic data. The published archive contains no customer records, personal data, API credentials, external URLs, or private chain-of-thought.

## Systems

| System | Role |
|---|---|
| P1 single prompt | Negative control using parametric model knowledge without corpus retrieval |
| P2 semantic RAG | Embedding search over Milvus followed by one selection prompt |
| P3 SupplierMind | Agentic pipeline with parsing, structured and semantic retrieval, compliance gating, and ranking |

P2 and P3 share the embedding model and vector index. They do not share the complete retrieval stack because P3 additionally applies structured filtering and compliance-aware processing.

## Duplicate-query correction

The original archived dataset contained 25 rows. Original Query 22 was character-for-character identical to Query 13, although it carried a different difficulty label. Query 22 was therefore removed before final analysis to avoid giving one query intent double weight.

The correction is post hoc and fully disclosed:

1. Original model outputs remain unchanged.
2. Only observations belonging to the duplicate query identifier are excluded.
3. Remaining queries are renumbered from 1 to 24 while preserving `source_query_number`.
4. Every metric, interval, diagnostic, ablation value, and figure is recomputed from the retained observations.
5. The original archive remains traceable through commit and file hashes in `thesis/PROVENANCE.json`.

The reason for exclusion is benchmark integrity, not the direction of the metric change.

## Metrics

- Precision@5 is the primary retrieval metric.
- MRR, Recall@5, Recall@10, nDCG@5, MAP@5, and Success@1 provide secondary ranking views.
- CSR reports the archived system-specific constraint score.
- Harmonized CSR rescoring applies the same deterministic supplier-profile checks to each system's returned identifiers.
- Verified Precision@5 counts relevant recommendations that also pass P3's evidence gate. It is reported as a governance-oriented usability metric, not a neutral cross-system ranking measure.
- Cost and latency are descriptive engineering measurements from the archived runs.

Confidence intervals and the P3 versus P2 comparison use query-level means. The analysis does not treat repeated observations from the same query as independent samples.

## Reproduce offline

Prerequisites are Python 3.11 and `uv`. No services or API credentials are required.

```bash
git clone https://github.com/nitishkpandey/SupplierMind.git
cd SupplierMind
cd apps/backend
uv sync --group dev
uv run python ../../thesis/scripts/reproduce.py
```

Alternatively, after backend dependencies are installed:

```bash
npm run thesis:reproduce
```

The command regenerates:

- `thesis/results/METRICS.json`
- `thesis/results/EXTRA_METRICS.json`
- `thesis/results/DIAGNOSTICS.txt`
- `thesis/results/ABLATION.txt`
- `thesis/results/ABSTENTION.txt`
- Figures 5.1 through 5.6 under `thesis/figures/`

It then checks the benchmark, archive sanitization, headline metrics, and provenance checksums.

## Expected headline results

| System | Precision@5 | 95 percent bootstrap interval |
|---|---:|---:|
| P3 SupplierMind | 0.747 | [0.633, 0.853] |
| P2 semantic RAG | 0.517 | [0.358, 0.675] |
| P1 single prompt control | 0.000 | [0.000, 0.000] |

The paired P3 minus P2 difference is `+0.230`, with a 95 percent bootstrap interval of `[0.123, 0.337]` across 24 query-level means and `p < 0.001`.

## Interpretation

The agentic advantage is strongest on the benchmark's medium and hard tiers. These tiers combine constraint count with selectivity, so they are not a pure controlled test of constraint count. H1 is therefore treated as partially supported.

P1's zero result is expected because the supplier names are synthetic and unavailable to a model using parametric knowledge alone. It is a construct control, not evidence that every retrieval system necessarily outperforms every general language model.

## Live reruns

A live rerun is not the default reproduction method. It requires the historical experimental implementation, PostgreSQL, Milvus, Redis, valid OpenAI and Voyage credentials, and paid calls. Because model generation and external services are stochastic, a live rerun can produce different observations and should be published as a new experiment rather than overwriting this archive.

## Provenance

`thesis/PROVENANCE.json` records source commits, model identifiers, archive counts, file sizes, and SHA256 hashes. Run the verifier directly with:

```bash
python thesis/scripts/verify_reproduction.py
```
