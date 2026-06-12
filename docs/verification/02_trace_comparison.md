# Verification 02: Demo Trace Comparison (Groq vs GPT-4o-mini)

**Date:** 2026-06-13
**Status:** PASS. Three new traces captured under `traces/gpt4o_mini/`, filenames
matching the Groq convention. Original Groq traces untouched.

| Trace | Groq (llama-3.1-8b-instant) | GPT-4o-mini |
|---|---|---|
| `task_3_1_react_trace.json` | 1 query, 5 iterations, mean latency 122,154 ms | 3 queries, 4-5 iterations each, mean latency 9,459 ms |
| `task_3_2_memory_trace.json` | 4/4 assertions pass; Q1 6 iters, Q2 6 iters | 4/4 assertions pass; Q1 5 iters, Q2 3 iters |
| `task_3_3_clarification_trace.json` | 3/5 assertions pass | 5/5 assertions pass |

## Task 3.1: ReAct Parser

Both providers reach `finish` without hitting the iteration cap. GPT-4o-mini is
roughly 13x faster end-to-end; the Groq mean is inflated by free-tier TPM pacing
waits rather than slower generation. GPT-4o-mini also completed three scenario
queries (simple, aerospace multi-constraint, geo-radius) where the Groq capture
covered one. Tool selection is comparable: geocode + cert canonicalisation +
industry inference, with `parse_quantity_unit` added when the query carries a
quantity.

## Task 3.2: Semantic Memory

Behaviourally identical outcome: on the follow-up query, both call
`lookup_past_query`, carry the Q1 constraints in the observation, reference the
memory in a later thought, and merge Q1 constraints with the new Q2 location in
the Finish payload. GPT-4o-mini does it with fewer iterations (Q2 in 3 vs 6),
i.e. it trusts the memory hit instead of re-deriving constraints with extra
tool calls.

## Task 3.3: Clarification Dialogue

The meaningful behavioural difference. Groq failed two of five assertions:
its opening clarification question did not mention the product, and the
turn-3 state never reached `complete`. GPT-4o-mini passes all five: asks a
product-specific question on turn 1, makes progress on turn 2, and produces
final constraints (including the certification) with `needs_clarification=False`
on turn 3.

**Thesis note:** this is a model-capability difference worth reporting, not a
code change. The clarification flow's quality depends on instruction-following
at low temperature; the 8B llama fallback degrades it gracefully rather than
breaking it.

## Cost

All three GPT-4o-mini captures together: roughly $0.005 (per `[llm-cost]` logs;
3.2 alone was $0.0024, 3.3 was $0.0014).
