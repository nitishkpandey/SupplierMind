# Verification 01: Provider Integration Check

**Date:** 2026-06-13 00:02 (local)
**Script:** `backend/scripts/provider_integration_check.py`
**Status:** PASS

## Provider selection

- Active client: `openai+groq-fallback` (`FallbackLLMClient`)
- Primary: `OpenAIProvider`, model `gpt-4o-mini` (served as `gpt-4o-mini-2024-07-18`)
- Fallback: `GroqProvider`, model `llama-3.1-8b-instant`, armed for retryable failures only
- Smoke completion `'provider-ok'` served by **openai**. Zero fallback events during the run.

## Pipeline run

- Query: `ISO 9001 certified packaging supplier in Germany, 5000 units per month`
- Parser (ReAct): 4 iterations, terminated by `finish`, tools used:
  `canonicalize_certification`, `geocode_location`, `parse_quantity_unit`
- Discovery: 27 candidates (semantic 10, SQL 20, geo 0)
- Compliance: 10 suppliers checked, 10 verdicts short-circuited deterministically, 0 LLM calls
- Ranking: 5 ranked, scores `[0.99, 0.99, 0.94, 0.94, 0.94]`
- Evaluator verdict: `auto_accept`
- End-to-end latency: **15,257 ms** (prior quota-dead attempt on 2026-06-12 took 237 s
  because every OpenAI call burned the retry budget before falling back to Groq;
  that defect was fixed the same day: `insufficient_quota` is now non-retryable
  but fallback-eligible)

## Returned suppliers (top 5)

Bremen Packaging Ltd., Cologne Packaging GmbH, Hannover Packaging AG,
Hannover Container AG, Stuttgart Packaging AG (first two at 0.99).
Full ranked list with IDs in the trace file.

## Cost

- Total estimated spend for the run: **$0.0012**
- Per-call costs logged via `[llm-cost]` lines (largest single call: $0.000406,
  the ReAct Finish iteration)

## Artefacts

- Trace: `traces/gpt4o_mini/pipeline_integration_run.json`
- The 2026-06-12 Groq-fallback run (quota-dead key, fallback chain proven live)
  is preserved separately at `traces/groq/pipeline_integration_run_quota_fallback.json`

## Warnings / notes

- None during the passing run.
- Environment gotcha recorded: a stale `OPENAI_API_KEY` inherited from the parent
  process environment overrides `backend/.env`; cleared per-session until next reboot.
