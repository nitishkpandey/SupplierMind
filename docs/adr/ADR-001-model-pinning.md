# ADR-001: Pin the OpenAI model to a dated snapshot

**Status:** Accepted (2026-06-13)

## Context

The system used the floating alias `gpt-4o-mini` as the primary model. OpenAI
repoints such aliases to newer builds over time, so a benchmark "on gpt-4o-mini"
is not reproducible: a re-run months later may hit a different model and produce
different numbers, with no record of the change.

Audit H also found two brittle couplings that make a naive pin dangerous:

1. **Cost table** (`app/core/llm.py`) keyed on the exact model string with a
   silent `return 0.0` for unknown models. Pinning to `gpt-4o-mini-2024-07-18`
   without updating the table would have billed every call at $0 — silently
   corrupting the benchmark's spend figures.
2. **Rate limiter** (`app/core/rate_limiter.py`) keyed on the exact model
   string with a conservative default fallback. A pinned snapshot would have
   silently dropped from 400 RPM / 180K TPM to 30 RPM / 6K TPM — over-throttling
   the benchmark.

The 2026-06-13 benchmark (`results/run_20260613/`) was executed against the
alias, which resolved to `gpt-4o-mini-2024-07-18` (verified against the live API
— the only gpt-4o-mini snapshot OpenAI publishes).

## Decision

1. **Pin** `OPENAI_MODEL_NAME` to `gpt-4o-mini-2024-07-18` in `config.py` and
   `.env.example` (and the runtime `backend/.env`).
2. **Cost table** gains an explicit `gpt-4o-mini-2024-07-18` entry plus a
   **prefix fallback** (`resolve_cost_rates`): a dated snapshot inherits its
   family's pricing. Unknown models now **raise `UnknownModelCostError`** rather
   than returning a silent 0.
3. **Rate limiter** `_caps` gains the same prefix fallback, so the pinned
   snapshot inherits the `gpt-4o-mini` limits.
4. **Two startup assertions** in `app/main.py`: refuse to boot if
   `OPENAI_MODEL_NAME` is not a dated snapshot (`is_pinned_snapshot`, regex
   `-\d{4}-\d{2}-\d{2}$`), or if it has no cost-table entry.

## Consequences

- **Positive:** the benchmark is reproducible against an exact model build;
  cost/throttle resolution is robust to future snapshots via prefix fallback;
  regressions (floating alias, missing cost entry) fail loud at boot, not
  silently mid-run.
- **Negative / maintenance:** upgrading to a newer snapshot is a deliberate,
  manual step — update the pin, add a cost-table entry if pricing changes, and
  re-run the benchmark. This is intended friction.
- The historical verification records (`docs/verification/04`,`05`,`06`) keep
  the run-time string they were written with; they are timestamps, not config.

## Alternatives considered

- **Floating alias + a version log:** record the resolved snapshot per run
  instead of pinning. Rejected — relies on discipline, and a mid-study repoint
  would still silently change results.
- **Pin without the cost/rate guards:** rejected — that is precisely the
  silent-$0 / over-throttle footgun Audit H identified.
