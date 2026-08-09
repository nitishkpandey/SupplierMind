# State-of-the-Art Comparison

This document positions SupplierMind against the current state of the art. It is
written to be lifted into the dissertation (it fits after related-work Section 3.6,
or as a subsection of the evaluation).

## Why this is a *positioning* comparison, not a leaderboard

A conventional state-of-the-art (SOTA) comparison runs several systems on one shared,
public benchmark and reports a single ranked table. That is **not possible** for this
task, for three reasons that are themselves the motivation for the thesis:

1. **No shared benchmark exists** for multi-constraint procurement supplier discovery.
   The established agent and retrieval benchmarks (SWE-bench, GAIA, AgentBench, BEIR,
   RAGAs) target other tasks and none measures auditability, so there is no leaderboard
   to compete on. Building one — SupplierBench-25 — is part of this contribution.
2. **Commercial procurement tools are closed** (e.g. Scoutbee, Keelvar, and the
   industry partner's own product): they run on proprietary data and cannot be
   executed against the synthetic corpus, so no apples-to-apples run is possible.
3. **One model was pinned** (`gpt-4o-mini-2024-07-18`) for reproducibility and cost
   control, so a frontier-model race was out of scope by design.

The comparison is therefore of two kinds: (a) a **measured** comparison against the
strongest *runnable* representatives of each paradigm, which was performed under
controlled conditions; and (b) a **capability positioning** against the best
approach in each broader class, grounded in the literature rather than in invented
numbers.

## What *was* measured (the controlled comparison)

RAG (P2) is the honest SOTA-of-practice proxy: it is the dominant pattern in current
procurement-AI products and shares its retrieval stack with SupplierMind, so any
difference is attributable to the architecture. All values are the mean of five runs
on SupplierBench-25 over the 10,000-supplier corpus.

| System (paradigm) | Precision@5 | Auditability (0–3) | Entity-hallucination | Correct abstention | Cost / query |
|---|---|---|---|---|---|
| Single-prompt LLM (P1) | 0.000 | 0 | 1.000 | 0.00 | $0.00020 |
| Keyword-SQL / manual search *(classical baselines, in code)* | run separately | 0 | ~0 | — | ~0 |
| **RAG — SOTA of practice (P2)** | **0.504** | 1 | ~0 | **0.80** | $0.00030 |
| Structured discovery + ranking, no verification *(P3 ablation)* | 0.427 | — | ~0 | — | — |
| **SupplierMind (P3)** | **0.731** | **3** | ~0 | 0.40 | $0.00140 |

Against the strongest runnable baseline (RAG), SupplierMind is **+0.227 Precision@5**
(95% CI [0.126, 0.330], p ≈ 0.000) and moves auditability from 1 to 3 — at ~4.7× the
cost, and while abstaining *worse* on impossible queries (0.40 vs 0.80), which is
reported openly.

## Capability positioning against the state of the art

The columns are the best approach in each class the field currently offers. Marks:
✓ = provides it; ◑ = partial / not guaranteed; ✗ = does not; — = not applicable.
Numbers are only shown where they were actually measured in this study.

| Capability | Frontier single-prompt LLM (+web) | Standard RAG (current products) | Advanced RAG (Self-RAG / rerank) | General LLM-agent frameworks (ReAct / AutoGen / MetaGPT) | Classical MCDM supplier selection (AHP / VIKOR / fuzzy) | **SupplierMind (P3)** |
|---|---|---|---|---|---|---|
| Parses a natural-language, multi-constraint query | ✓ | ◑ | ◑ | ✓ | ✗ | ✓ |
| Grounds in the buyer's **private governed** data | ✗ | ✓ | ✓ | ✗ | ✓ (given table) | ✓ |
| Enforces **hard** constraints exactly (numeric / categorical / geospatial) | ◑ | ✗ | ◑ | ◑ | ✓ | ✓ |
| **Per-claim** verification against quoted evidence | ✗ | ✗ | ◑ | ✗ | ✗ | ✓ |
| Entity-hallucination control | ✗ | ✓ | ✓ | ◑ | ✓ | ✓ (~0) |
| Correct abstention on impossible queries | ◑ | ◑ (0.80) | ◑ | ✗ | ✗ | ◑ (0.40) |
| Sanctions + address screening of new suppliers | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |
| Queryable **audit trail** (EU AI Act-style record-keeping) | ✗ | ◑ (1) | ◑ | ◑ | ◑ | ✓ (3) |
| Deterministic, reproducible ranking | ✗ | ✓ | ◑ | ✗ | ✓ | ✓ |
| Multi-constraint Precision@5 *(measured here)* | 0.000\* | 0.504 | not run | not applied to task | — | **0.731** |
| Relative cost / latency | low | low | medium | high | negligible | high (~4.7× RAG) |

\* The single-prompt figure is the measured P1 result against the corpus; a stronger
model would name suppliers more fluently but still cannot ground in the buyer's
private data (see the hallucination probe in Section 5.4), so the *architectural* gap
remains.

### How to read the row-by-row story
- **Frontier single-prompt LLM (+web)** is the best *naming* tool and is genuinely
  strong at producing plausible suppliers with links. But it cannot search the
  buyer's private governed data (and, for confidentiality, usually must not be sent
  it), it asserts constraints rather than verifying them, and it produces a chat
  transcript, not an audit trail. It wins on convenience, not on trust.
- **Standard RAG** is the state of practice and the fair yardstick: grounded and
  cheap, but with no hard-constraint enforcement, no per-claim verification, and only
  a shallow audit trail — which is exactly why its precision collapses on hard,
  multi-constraint queries.
- **Advanced RAG** (Self-RAG, cross-encoder rerankers) improves ranking and adds a
  self-critique step, so it would likely beat plain RAG on ordering; but it still does
  not *enforce* numeric/categorical thresholds or produce a per-constraint,
  evidence-linked audit record. It is the most important missing numerical baseline
  and is proposed below.
- **General LLM-agent frameworks** supply the mechanisms SupplierMind uses (ReAct,
  tools, multi-agent, self-reflection) but are demonstrated on software engineering
  and web tasks, are not tied to a procurement data model, and do not treat
  auditability as a measured property.
- **Classical MCDM supplier selection** solves the ranking rigorously but assumes the
  candidate set and its attributes are already tabulated; it has no natural-language
  front end, no discovery, and no evidence verification.
- **SupplierMind** is the only column that combines language understanding, grounding
  in governed data, exact hard-constraint enforcement, per-claim verification,
  sanctions screening, and a queryable audit trail — and, among the runnable systems,
  it has the highest measured multi-constraint precision. Its honest weaknesses are
  cost and its weaker abstention.

## The honest bottom line

SupplierMind is **not claimed to be state of the art in an absolute, leaderboard
sense** — no such leaderboard exists, and it was not raced against frontier models.
The defensible claim is narrower and stronger: *against the strongest runnable
representative of current practice (RAG), under identical conditions, it is
significantly more precise and far more auditable; and across the broader landscape it
occupies a capability position that no existing class of system fully covers.*

## How to strengthen this into a numerical SOTA comparison (next experiments)

1. **Classical baselines (runnable now, no API cost).** Execute the keyword-SQL and
   manual-search baselines already implemented in
   `apps/backend/app/evaluation/baselines.py` on SupplierBench-25 and add their
   Precision@5 to the measured table:
   ```bash
   docker compose -f infra/docker/docker-compose.yml up -d
   cd apps/backend
   uv run python ../../thesis/scripts/run_10k_benchmark.py --baselines
   ```
2. **Advanced-RAG rung (moderate effort).** Add a cross-encoder reranker (or a
   Self-RAG-style critique) on top of P2's retrieval to create a "RAG++" baseline.
   This is the single most valuable *runnable* addition, because it tests whether a
   stronger retriever — rather than the verification gate — could close the gap.
3. **Cross-model / frontier comparison (definitive; needs paid API access).** Re-run
   P1 and P2 with GPT-4o / Claude / a web-search agent through the provider
   abstraction (`app/core/config.py` → `OPENAI_MODEL_NAME`). This is the experiment
   that would let the study make a genuine frontier-model claim; it is flagged as the
   most valuable future work and is blocked only by paid access, not by design.
