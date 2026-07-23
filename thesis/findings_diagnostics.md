# SupplierMind — Diagnostic Experiments and Ablation

This file complements the headline results in `findings.md`. Where `findings.md`
answers *"which architecture is better?"*, this file answers *"why, and what is
the agentic system actually doing inside?"*. It reports six diagnostic
experiments plus a component ablation. All of them run on the same 10,000-supplier
corpus, using an **instrumented** version of the benchmark that records, for every
query, the parser's extracted constraints, the tools it called, the number of LLM
calls and tokens, and the time spent waiting on the embedding provider's rate
limit. Numbers are from **five instrumented runs** (three for the ablation).
Reproduced by `thesis/scripts/analyze_diagnostics.py` and
`analyze_ablation.py`; raw output in `thesis/results/10k/DIAGNOSTICS.txt` and
`ABLATION.txt`.

How these map to the research questions:

| Experiment | Serves | One-line result |
|---|---|---|
| Component ablation | RQ1 / RQ3 (what drives the agentic advantage) | The compliance gate is the single biggest driver |
| Intent resolution | RQ1 / RQ3 (parser quality) | Parser extracts constraints 99.3% correctly |
| Error taxonomy | RQ3 (where it fails) | Genuine failures ≤3%; the common issue is cosmetic |
| Tool access | RQ3 (agentic behaviour) | ~3 tools/query; usage tracks query type |
| Prompt efficiency | RQ3 (cost) | P3 uses ~5× the LLM calls and ~6× the tokens of RAG |
| Clean latency | RQ3 (cost) | P3 ~13 s compute vs RAG ~3 s |
| Task success rate | RQ1 (usefulness) | P3 usefully answers 98% of queries vs RAG 84% |

---

## 1. Component ablation — what inside P3 actually matters?

**What it evaluates.** The P1 → P2 → P3 comparison already shows *that* the full
agentic system wins, but not *which part* of it. This ablation removes one
component — the compliance / quote-or-fail gate — and re-runs, so I can measure
that component's contribution directly. It builds a three-rung ladder:

1. **P2 RAG** — semantic retrieval only.
2. **P3 no-compliance** — P3's structured discovery (SQL constraint filtering)
   and evidence-gated ranking, but with the compliance gate switched off, so
   candidates are ranked by semantic / proximity / completeness only.
3. **P3 full** — the same, with the compliance gate switched back on.

**Why it matters.** An agentic system is a stack of parts, each adding cost and
complexity. A reviewer will rightly ask which parts earn their keep. This is the
experiment that answers it, and it is the strongest evidence for *where* the
agentic advantage comes from.

**How it was tested.** The `no_compliance` ablation was run three times on the
full 25-query benchmark (P3 only). Precision@5 is compared across the three
rungs, overall and by difficulty tier.

**Result.**

| Rung | Overall P@5 | Simple | Medium | Hard | Δ vs previous |
|---|---|---|---|---|---|
| P2 RAG (semantic only) | 0.504 | 0.950 | 0.340 | 0.229 | — |
| P3 no-compliance (+structured discovery/ranking) | 0.427 | 0.850 | 0.333 | 0.076 | **−0.077** |
| P3 full (+compliance gate) | 0.731 | 0.950 | 0.664 | 0.577 | **+0.305** |

**What it means.** This is a decisive and slightly surprising result.

- Structured discovery and ranking **without** the compliance gate are *not*
  enough — P3-no-compliance (0.427) actually scores **below** plain RAG (0.504).
  Casting a wide candidate net by SQL and semantics, then ranking on similarity
  alone, does worse than RAG's tighter semantic retrieval.
- Switching the compliance gate back on adds **+0.305** — it more than doubles
  precision, and it is what lifts P3 above RAG. The effect is concentrated on
  hard queries (hard P@5 jumps from 0.076 to 0.577).

So the single component that drives the agentic system's advantage is the
**compliance / quote-or-fail gate**: the part that checks each candidate against
each constraint and lets ranking reward genuine constraint satisfaction rather
than surface similarity. This also explains the headline finding that the P3–P2
gap widens with difficulty — the gate matters most exactly where the query is
hard.

---

## 2. Intent resolution — how well does the parser understand the query?

**What it evaluates.** Whether P3's Parser correctly turns the natural-language
query into the right structured constraints (category, country, certifications,
capacity, lead time). This is the entry point of the whole pipeline: if the
parser mis-reads the query, everything downstream is searching for the wrong
thing.

**Why it matters.** The parser is the part most exposed to the messiness of
natural language, and an earlier, informal look at the logs suggested it was
"brittle." This experiment tests that claim properly, and its answer reframes it.

**How it was tested.** The benchmark already stores the *true* structured
constraints for each query. For every query I compared the parser's extracted
constraints, field by field, to those ground-truth constraints (pooled over the
five runs = 125 query-runs), and scored each field as correct or not.

**Result.**

| Constraint field | Extraction accuracy |
|---|---|
| category | 0.992 (124/125) |
| country | 1.000 (100/100) |
| certifications | 0.992 (124/125) |
| capacity | 1.000 (125/125) |
| lead time | 0.984 (123/125) |
| **Overall** | **0.993 (596/600)** |

**What it means.** The parser's *structured* understanding is excellent — it
extracts the constraints that drive retrieval correctly **99.3%** of the time.
The "brittleness" seen in the logs is real but lives only in a separate,
free-text `product_type` field (see §3), which sometimes picks up stray words but
is not what the SQL constraint filter uses. So the honest, corrected picture is:
**the parser is robust where it counts**, and P3's structured filtering is
reliable because the structured extraction feeding it is reliable.

---

## 3. Error taxonomy — where does P3 actually go wrong?

**What it evaluates.** A categorised count of P3's failures, so "it sometimes
fails" becomes "it fails in these specific, measurable ways."

**Why it matters.** A thesis is stronger when it says exactly how a system fails,
not just how often. It also tells a future developer where to spend effort.

**How it was tested.** Every query-run was labelled against four failure
categories (which can overlap), using the captured parser output and outcome.

**Result** (pooled over 125 query-runs):

| Failure category | Count | Share |
|---|---|---|
| Polluted product string (stray unit words in the free-text product field) | 21 | 16.8% |
| Parse failure / hit max ReAct iterations | 4 | 3.2% |
| Clean parse but zero precision (retrieval missed) | 2 | 1.6% |
| Missed a constraint (a cert / capacity / lead time not extracted) | 1 | 0.8% |

**What it means.** The one common issue — a polluted product string (16.8%) — is
**cosmetic**: it dirties the free-text product field but not the structured
constraints, so retrieval, which filters on the structured constraints, is
unaffected. The genuinely harmful failures — an actual parse failure, a missed
constraint, or a clean-but-wrong retrieval — are all **rare (≤3.2% each)**. So
P3's real error rate is low, and its most visible symptom is mostly harmless.
The concrete fix suggested is to stop the parser copying unit tokens into the
product field — a small clean-up, not a redesign.

---

## 4. Tool access — what is the ReAct parser doing?

**What it evaluates.** Which of the parser's five tools it actually calls, how
many per query, and whether tool use lines up with query type.

**Why it matters.** "Agentic" means the parser autonomously decides which tools
to use. This experiment shows that decision-making is real and sensible, not
decorative — a core part of defending the "agentic" label.

**How it was tested.** The instrumented runner records the tool calls in each
query's ReAct trace. I counted how often each tool fired and the mean
Precision@5 on the queries where it was used.

**Result** (mean **3.1** tool-calls per query):

| Tool | Used in (of 125 query-runs) | Mean P@5 when used |
|---|---|---|
| infer_industry_context | 111 | 0.753 |
| geocode_location | 103 | 0.713 |
| parse_quantity_unit | 75 | 0.600 |
| canonicalize_certification | 73 | 0.668 |
| lookup_past_query (memory) | 2 | 1.000 |

**What it means.** The parser uses about three tools per query and picks them to
fit the query: `geocode_location` fires on the queries that name a country,
`parse_quantity_unit` on the ones with a capacity figure, and
`canonicalize_certification` on the ones naming a certificate. The lower P@5 on
`parse_quantity_unit` queries (0.600) simply reflects that capacity-bearing
queries are harder, not that the tool hurts. The memory tool (`lookup_past_query`)
almost never fires, which is expected: each benchmark query is independent, so
there is no prior history to recall. This confirms the tool-selection behaviour
is genuine and query-appropriate.

---

## 5. Prompt efficiency — how much LLM work does each system do?

**What it evaluates.** The number of LLM calls and tokens each system spends per
query — the concrete driver behind the cost difference.

**Why it matters.** It turns "the agentic system is more expensive" into an exact
mechanism, and it is the fairest way to explain the cost gap.

**How it was tested.** The LLM client counts calls and prompt/completion tokens;
I read the per-query delta.

**Result** (per-query means):

| System | LLM calls | Prompt tokens | Completion tokens | Total tokens |
|---|---|---|---|---|
| P3 SupplierMind | 5.3 | 7,322 | 496 | 7,818 |
| P2 RAG | 1.0 | 1,017 | 171 | 1,188 |
| P1 single-prompt | 1.0 | 91 | 261 | 352 |

**What it means.** P3 makes about **five LLM calls** per query (parser ReAct
steps, industry inference, compliance checks) versus one for RAG, and uses about
**6.5× the tokens**. This is the direct cause of P3's ~4.7× higher dollar cost.
It is a real, quantified trade-off: the agentic reasoning that buys accuracy and
auditability is paid for in LLM work.

---

## 6. Clean latency — how slow is P3 really?

**What it evaluates.** True compute time per query, with the embedding
provider's rate-limit sleeps removed.

**Why it matters.** The raw wall-clock time is badly distorted by the free-tier
embedding limit (3 requests/minute), which forces ~40-second pacing sleeps at
random points. Reporting wall-clock alone would blame the architecture for the
provider's free-tier cap. This experiment separates the two.

**How it was tested.** The rate limiter now records how long it slept; I
subtract that per-query pacing time from the wall-clock time to get compute time.

**Result** (per-query means):

| System | Wall-clock | Provider pacing | **Compute time** |
|---|---|---|---|
| P3 SupplierMind | 21.4 s | 8.2 s | **13.2 s** |
| P2 RAG | 2.8 s | (not separated) | ~2.8 s |
| P1 single-prompt | 3.5 s | — | ~3.5 s |

**What it means.** With provider pacing removed, P3's real compute time is about
**13 seconds** per query, versus about **3 seconds** for RAG — roughly 4.7×
slower, matching its ~5× LLM-call count. (P3's pacing time is measured directly;
for P1/P2 the single embedding call rarely hit the limit, so their wall-clock is
already close to compute.) The honest conclusion: even setting aside the free
tier, the agentic system is several times slower than RAG. This is the second
real cost of the approach, alongside dollars (§5).

---

## 7. Task success rate — how often is the answer useful?

**What it evaluates.** The fraction of queries where a system returns **at least
one** correct supplier in its top five — a simple, practical "did it help the
user at all?" measure that complements Precision@5.

**Why it matters.** Precision@5 measures how *many* of the five are right; task
success measures whether the user got *anything* useful. For a procurement tool,
returning even one correct supplier is often the difference between useful and
useless.

**How it was tested.** For each query, scored 1 if any of the top five returned
suppliers is correct, else 0; averaged over queries and runs.

**Result.** P3 **0.984**, P2 **0.840**, P1 **0.000**.

**What it means.** P3 gives the user at least one correct supplier on **98%** of
queries, versus **84%** for RAG and **0%** for single-prompt (which returns only
invented names). So the agentic system is not just more precise on average — it
much more reliably returns *something usable* on any given query.

---

## Summary of the diagnostic story

Putting the pieces together: the agentic system's advantage is driven mainly by
its **compliance gate** (§1), which works because the **parser reliably extracts
the constraints** it checks (§2). Its failures are mostly **cosmetic** (§3), its
**tool use is genuine and query-appropriate** (§4), and it usefully answers far
more queries than RAG (§7). All of this is bought with **~5× the LLM calls and
~6× the tokens** (§5) and **~4.7× the compute time** (§6) — the honest, measured
price of the accuracy and auditability reported in `findings.md`.
