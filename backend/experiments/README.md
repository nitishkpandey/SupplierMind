# Three-Paradigm Benchmark Experiments

Phase 2 of the Development Plan (10 June 2026). Three paradigms answer the
same SupplierBench-25 queries; the comparison is the core empirical
contribution of the thesis.

| Paradigm | What it is | Code |
|---|---|---|
| P1 | Single-prompt LLM, parametric knowledge only | `paradigm1_singleprompt.py` |
| P2 | Minimal RAG: retrieve top-k, one prompt, pick 5 | `paradigm2_rag.py` |
| P3 | SupplierMind multi-agent system | the application (`app/`) |

All three run on OpenAI gpt-4o-mini-2024-07-18 via `app/core/llm.py`
and emit the same output shape
(`ParadigmResult`): top-5 supplier names + ids + per-pick reasoning + latency.

## Design decisions (deliberate, documented for the thesis)

**P1 does NOT see the corpus.** It is the pure parametric-knowledge baseline:
one prompt, no retrieval, no tools. Consequently it cannot emit corpus
supplier ids (`supplier_ids` is always empty) and corpus-overlap metrics
(P@5, MRR) measure exactly how far parametric knowledge gets you on a private
corpus: the expected answer is "nowhere", and that is the point of the
baseline. Name-level fuzzy matching against the corpus is computed by the
benchmark harness for completeness.

**P2 is deliberately minimal.** Top-k retrieval (k=10 by default) with the
SAME Voyage embeddings and Milvus index P3 uses, one templated prompt, no
compliance gate, no verification loop, no clarification dialogue, no ranking
heuristics. Any quality delta between P2 and P3 is therefore attributable to
the agentic machinery, not to a different retrieval stack.

**Chunking: one document per supplier.** Supplier records are short and
atomic; per-supplier chunks keep citations unambiguous and make the
candidate list the LLM sees identical in granularity to what P3's discovery
agent consumes.

**No code sharing with P3.** The baselines do not import agent code. The
duplication is intentional: each paradigm must be readable as a standalone
description of its method section.

## Running

```bash
cd backend

# P1 on a sample query (LLM key required; no databases needed)
uv run python -m experiments.paradigm1_singleprompt "ISO 9001 packaging supplier in Germany"

# P2 on a sample query (needs Milvus + Postgres up: docker compose up -d)
uv run python -m experiments.paradigm2_rag "ISO 9001 packaging supplier in Germany"
```

Unit tests (no live services):

```bash
uv run pytest tests/unit/test_paradigm_baselines.py -q
```

## Output shape

```python
ParadigmResult(
    paradigm="P2-rag",
    raw_query="...",
    supplier_names=["...", ...],   # up to 5
    supplier_ids=["uuid", ...],    # [] for P1 (no corpus access)
    reasoning=["...", ...],        # one entry per pick
    exec_ms=1234,
    error=None,                    # provider/parse failures recorded, not raised
    extra={...},                   # paradigm-specific diagnostics
)
```
