# SupplierMind Architecture

Deep dive on the agentic system (Paradigm 3) plus the architectural shape of
the two baseline paradigms it is benchmarked against.

## Paradigm overviews

### P1 — single-prompt LLM

```
user query ──> LLM (one prompt, parametric knowledge) ──> 5 names + reasoning
```

No corpus, no tools, no retrieval. `backend/experiments/paradigm1_singleprompt.py`.

### P2 — minimal RAG

```
user query ──> Voyage embed ──> Milvus top-10 ──> one LLM prompt ──> pick 5 (ids)
```

Same embedding model and vector index as P3, nothing else.
`backend/experiments/paradigm2_rag.py`.

### P3 — SupplierMind (the system)

```
user query
   │
Parser (ReAct loop over a tool registry; semantic memory; clarification gate)
   │            └── may PAUSE: pending_clarifications row + SSE event;
   │                user answers via POST /queries/{id}/clarify and the
   │                pipeline resumes with the enriched query
External Discovery (scope=both only: Tavily, Wikidata, OpenSanctions → auto-ingest)
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

## The five agents

| Agent | Role | LLM use |
|---|---|---|
| Parser | ReAct loop: Thought → Action (tool) → Observation, max 6 iterations; emits structured `ParsedConstraints` | yes (loop + tools) |
| Discovery | Hybrid retrieval: Milvus similarity + SQL constraint filters; three-tier scope (approved / my-list / discovered) | no |
| Compliance | Builds a per-supplier × per-constraint matrix; every claimed fact must quote stored evidence or fail | yes (extraction) |
| Ranking | Deterministic weighted scoring + human-readable explanations | template only |
| Evaluator | Judges result quality; can send the pipeline back to discovery with feedback (bounded retries) | yes |

### Parser tool registry (Task 3.1)

`backend/app/agents/tools/`: `geocode_location` (Nominatim), `canonicalize_certification`
(taxonomy), `infer_industry_context` (small LLM call), `parse_quantity_unit`
(deterministic regex), `lookup_past_query` (per-user Milvus memory, Task 3.2).

Loop hygiene, each added after a failure observed in live smoke runs:
stop-sequences against hallucinated Observations; same-args dedup; per-tool
budget (2 executions); force-finish instruction on the final iteration;
trace-aware fallback extraction; pre-loop gate that raises a clarification
for contentless queries instead of spending the ReAct budget.

### Semantic memory (Task 3.2)

Separate Milvus collection `query_memory` (512-dim Voyage embeddings, cosine,
scalar-indexed by user). Written only for evaluator-accepted runs at
`finalize`; read through the closure-bound `lookup_past_query` tool, so the
LLM physically cannot query another user's history. Right-to-be-forgotten:
`DELETE /api/v1/users/me/memory`.

### Multi-turn clarification (Task 3.3)

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
3. **Discovered** — auto-ingested from external discovery; quarantined until
   a human approves with a written justification (HITL; 422 on thin
   justifications).

Cross-user access is answered with 404 (not 403) so existence cannot be probed.

## Audit log

Every agent run writes an `audit_logs` row: agent, action, reasoning,
input/output snapshots, duration. The Parser's snapshot carries the full
ReAct trace; clarifications log under `clarification_handler`; memory writes
under `memory_service`. `/admin/metrics` aggregates latency, throttle events,
recent errors, and the active LLM provider with estimated spend.

## LLM provider layer

`backend/app/core/llm.py`: `LLMProvider` protocol; `OpenAIProvider`
(gpt-4o-mini-2024-07-18, pinned snapshot) is the only provider. The
`LLMProvider` Protocol is retained for future portability — a different
OpenAI-compatible backend (Azure OpenAI, etc.) can be swapped in without
touching the agents — but there is no runtime fallback: an OpenAI failure that
survives the per-provider tenacity retries propagates as a clear error. Groq
was removed in Phase C (see `docs/adr/ADR-002-single-provider-deployment.md`);
auth/quota errors surface immediately. Per-call cost estimates accumulate into a
process-wide total. Request pacing lives in `rate_limiter.py` (per-model
sliding windows keyed by RPM + TPM).
