# ADR-002: Single-provider deployment (drop Groq, keep the abstraction)

**Status:** Accepted (2026-06-14)

> Referred to as "ADR-005" in earlier planning notes; renumbered to ADR-002 to
> stay sequential after ADR-001 (no ADR-003/004 exist yet).

## Context

The system shipped with two LLM providers: `OpenAIProvider` (primary) and
`GroqProvider` (llama-3.1-8b-instant), wrapped by a `FallbackLLMClient` that
fell back to Groq on retryable OpenAI failures.

Two problems made the dual-provider setup a net liability for a thesis-grade
system:

1. **Silent cross-model degradation.** The 2026-06-13 "contaminated run"
   executed entirely on Groq because a stale `OPENAI_API_KEY` shadowed the real
   one and the wrapper fell back silently — producing llama-3.1-8b numbers that
   looked like a valid benchmark. A fallback that swaps in a *different model
   class* without a loud signal is a footgun, not a safety net.
2. **Two of everything.** Groq doubled the cost-table keys, rate-limiter
   entries, env vars, and provider-selection branches — all of which Audit H
   flagged as brittle (exact-match lookups that silently mis-resolve).

## Decision

Remove Groq entirely; OpenAI is the only provider. **Keep** the `LLMProvider`
Protocol and the `build_llm_client` selection seam so a future
OpenAI-compatible backend (Azure OpenAI, a self-hosted gateway) can be swapped
in without touching the agents.

Concretely (Phase C):
- Deleted `GroqProvider`, `FallbackLLMClient`, `_should_fall_back`; re-pointed
  the `LLMClient` alias to `OpenAIProvider`; `build_llm_client` returns a bare
  `OpenAIProvider`.
- Removed llama-* cost-table and rate-limiter entries; removed `GROQ_API_KEY`,
  `GROQ_FALLBACK_MODEL_NAME`, `LLM_MODEL_NAME` from settings; `LLM_PROVIDER` is
  now `Literal["openai"]`.
- Removed the `groq` dependency.
- Renamed the admin-metric fields `groq_*` → `throttle_*` (dashboard no longer
  contradicts the code).

## Consequences

- **Positive:** one provider, one model, far less config surface; the
  silent-fallback failure mode is structurally impossible — an OpenAI failure
  that survives tenacity retries now raises a clear error.
- **Negative — single point of failure.** An OpenAI outage takes the system
  down with no automatic backup. **Accepted** for a thesis-grade demo system:
  loud failure is preferable to silent degradation to a weaker model, and the
  retained abstraction makes adding a *same-class* backup (Azure OpenAI) a small
  future change if ever needed.
- The provider-neutral `ModelRateLimiter` throttles OpenAI calls by model
  family and dated snapshot.

## Alternatives considered

- **Keep Groq as fallback.** Rejected — the contaminated-run incident showed a
  cross-model fallback masks misconfiguration; the safety it buys is illusory
  for a benchmark.
- **Swap Groq for Azure OpenAI (real same-class redundancy).** Deferred — more
  credentials/cost setup than a thesis demo warrants; the abstraction leaves the
  door open.
- **Self-hosted open model.** Out of scope (infra burden).
