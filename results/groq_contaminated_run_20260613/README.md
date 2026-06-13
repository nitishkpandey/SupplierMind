# Contaminated benchmark run — DO NOT USE for thesis numbers

Archived from `backend/data/` on 2026-06-13.

This 25/25 run (run_id ee3d708b, finished 2026-06-13 02:24 local) was launched
from a shell that still carried a stale, quota-dead `OPENAI_API_KEY` inherited
from the harness parent process. The env var overrode the working key in
`backend/.env`, so every OpenAI call returned 429 `insufficient_quota` and the
`FallbackLLMClient` served **all 253 LLM calls from Groq (llama-3.1-8b-instant)**.

Evidence: `results/full_benchmark_rerun_20260613_005209.err.log` contains 253
`[llm-fallback]` warnings (quota 429) and zero `[llm-cost]` lines; all
`cost_usd` fields are 0.0 and SupplierMind latency medians ~184 s/query
(Groq free-tier pacing).

The numbers are internally consistent but reflect llama-3.1-8b, not
gpt-4o-mini, so they cannot be presented as the GPT-4o-mini benchmark.
Kept only as a provider-fallback robustness artifact.
