# SupplierMind Architecture

Deep dive on the agentic system (Paradigm 3) plus the architectural shape of
the two baseline paradigms it is benchmarked against.

## Paradigm overviews

### P1 — single-prompt LLM

```
user query ──> LLM (one prompt, parametric knowledge) ──> 5 names + reasoning
```

No corpus, no tools, no retrieval. `apps/backend/experiments/paradigm1_singleprompt.py`.

### P2 — minimal RAG

```
user query ──> Voyage embed ──> Milvus top-10 ──> one LLM prompt ──> pick 5 (ids)
```

Same embedding model and vector index as P3, nothing else.
`apps/backend/experiments/paradigm2_rag.py`.

During thesis evaluation, P2 retrieval is filtered at the vector-store layer
to the frozen SupplierBench curated supplier IDs. Normal product searches leave
that allowlist unset and can use the full active supplier database.

### P3 — SupplierMind (the system)

```
user query
   │
Parser (ReAct loop over a tool registry; semantic memory; clarification gate)
   │            └── may PAUSE: pending_clarifications row + SSE event;
   │                user answers via POST /queries/{id}/clarify and the
   │                pipeline resumes with the enriched query
External Discovery (scope=both only: Tavily, Geoapify, OpenSanctions -> pending review)
   │
Internal Discovery (Milvus semantic search + PostgreSQL constraint filtering)
   │
Compliance (per-candidate constraint matrix; quote-or-fail evidence discipline)
   │
Ranking (deterministic weighted scoring: constraint/semantic/proximity/completeness)
   │
Evaluator (accept / retry-with-feedback loop, bounded)
   │
finalize (write accepted query to per-user semantic memory in Milvus)
```

Every model or embedding operation inside this flow crosses the AI policy
gateway:

```
query / job / evaluation
   -> bound AIRequestContext (purpose, classification, IDs, limits)
   -> policy + per-call/per-query budget checks
   -> AIGateway or EmbeddingGateway
   -> OpenAI or Voyage transport
   -> content-free ai_usage_events row in PostgreSQL
   -> admin metrics API and dashboard
```

The transport is never invoked when classification or budget policy denies a
call.

## The five agents

| Agent | Role | LLM use |
|---|---|---|
| Parser | ReAct loop: Thought → Action (tool) → Observation, max 6 iterations; emits structured `ParsedConstraints` | yes (loop + tools) |
| Discovery | Hybrid retrieval: Milvus similarity + SQL constraint filters; three-tier scope (approved / my-list / pending review) | no |
| Compliance | Builds a per-supplier × per-constraint matrix; every claimed fact must quote stored evidence or fail | yes (extraction) |
| Ranking | Deterministic weighted scoring + human-readable explanations | template only |
| Evaluator | Judges result quality; can send the pipeline back to discovery with feedback (bounded retries) | yes |

### Parser tool registry

`apps/backend/app/agents/tools/`: `geocode_location`, `canonicalize_certification`
(taxonomy), `infer_industry_context` (small LLM call), `parse_quantity_unit`
(deterministic regex), `lookup_past_query` (per-user Milvus memory).

Loop hygiene, each added after a failure observed in live smoke runs:
stop-sequences against hallucinated Observations; same-args dedup; per-tool
budget (2 executions); force-finish instruction on the final iteration;
trace-aware fallback extraction; pre-loop gate that raises a clarification
for contentless queries instead of spending the ReAct budget.

### Semantic memory

Separate Milvus collection `query_memory` (512-dim Voyage embeddings, cosine,
scalar-indexed by user). Written only for evaluator-accepted runs at
`finalize`; read through the closure-bound `lookup_past_query` tool, so the
LLM physically cannot query another user's history. Right-to-be-forgotten:
`DELETE /api/v1/users/me/memory`.

### Multi-turn clarification

System-level pause/resume — not chat history. A raised clarification is a
`pending_clarifications` row (max 3 turns, DB CHECK enforced); the pipeline
parks the query in `pending`, the frontend renders the question inline, and
`POST /queries/{id}/clarify` re-enters the pipeline with the enriched query
and the previous turn's partial constraints. Degraded parses never pause:
without a resumable row the query fails gracefully with the question as the
error message.

## Three-tier governance

1. **Approved** — org-level, admin-curated; default search scope.
2. **My suppliers** — personal saves, user-scoped.
3. **Pending review** — web-discovered suppliers with verified city/country
   and sanctions screening metadata. They remain visible in the query that
   discovered them when they clear the ranking threshold, but they are
   quarantined from benchmark/evaluation corpora and company-approved lists
   until a human approves with a written justification (HITL; 422 on thin
   justifications).

External discovery intentionally keeps the location stack small: Geoapify
Geocoding validates extracted page locations or company-plus-query context;
Geoapify Places is the second path when the page has no usable address. Web
suppliers without a verified city, country, and coordinates are rejected before
ingestion so the UI does not show `null` locations.

Cross-user access is answered with 404 (not 403) so existence cannot be probed.

## Production vs thesis corpus control

The product application can search every active supplier row: approved
database suppliers, the 10k synthetic scale set, personal saves, and eligible
pending-review web discoveries when the user chooses web discovery.

The thesis evaluator intentionally does not use that dynamic corpus. It loads
the frozen IDs from `apps/backend/data/suppliers_synthetic.json` through
`app.evaluation.corpus.benchmark_supplier_ids()` and passes them into P1/P2/P3
retrieval. SQL baselines use `Supplier.id IN (...)`; Milvus/Chroma searches use
the same optional allowlist before candidate ranking. This keeps SupplierBench
metrics reproducible even after product-scale data is loaded.

## AI data egress and budgets

SupplierMind classifies every provider-bound payload:

| Classification | Product meaning | External default |
|---|---|---|
| `public` | Public supplier or web information | allowed |
| `internal` | Ordinary Mercanis procurement queries and supplier metadata approved for the configured processors | allowed |
| `confidential` | Customer-confidential documents, contracts, commercial terms, or personal data | denied |
| `restricted` | Secrets, credentials, regulated/high-impact data, and the unbound fallback | denied |

The allow list is configurable, but enabling confidential external processing
requires documented Security and Legal approval. An unbound context is
`restricted`, so a missed binding fails closed with
`classification_not_allowed`.

Text calls enforce a configurable 32,000-token and $0.10 per-call default.
Calls in one query share a configurable $0.50 ledger. Estimated cost is reserved
before the transport call and settled to actual cost afterward; concurrent
calls cannot oversubscribe the ledger. A resumed clarification reloads known
spend from `ai_usage_events`, so pausing does not reset the budget. Embeddings
enforce the token limit. Voyage cost remains null until an authoritative price
calculation exists and is reported as unknown rather than zero.

See `docs/adr/ADR-003-ai-data-egress-and-usage.md` for the decision and approval
rules.

## Audit and AI usage records

Every agent run writes an `audit_logs` row: agent, action, reasoning,
input/output snapshots, duration. The Parser's snapshot carries the full
ReAct trace; clarifications log under `clarification_handler`; memory writes
under `memory_service`.

AI provider telemetry is separate and content-free. `ai_usage_events` contains
purpose, classification, operation, provider/model, units, nullable cost,
latency, outcome, redaction/excerpt flags, and correlation identifiers. It does
not contain prompts, responses, or document excerpts. PostgreSQL is the source
of truth for `/admin/metrics`, whose admin-only dashboard distinguishes known
cost from unknown-cost calls and shows denials, failures, provider/purpose
breakdowns, and links to the highest-cost authorized queries.

## LLM provider layer

`apps/backend/app/platform/ai/gateway.py` is the mandatory policy and usage
boundary. `apps/backend/app/core/llm.py` retains the `LLMProvider` protocol and
the `OpenAIProvider` transport (gpt-4o-mini-2024-07-18, pinned snapshot).
`build_llm_client()` returns an `AIGateway` wrapping that transport.

The protocol is retained for future portability — a different OpenAI-compatible
backend (Azure OpenAI, etc.) can be swapped in without touching the agents —
but there is no runtime fallback: an OpenAI failure that survives the
per-provider tenacity retries propagates as a clear error; auth/quota errors
surface immediately. See
`docs/adr/ADR-002-single-provider-deployment.md` for the architectural decision
to retain the provider abstraction without a second provider wired and ADR-003
for the gateway boundary. Request pacing lives in `rate_limiter.py` (per-model
sliding windows keyed by RPM + TPM); durable cost and usage reporting comes from
PostgreSQL rather than the transport's process-local diagnostic counter.
