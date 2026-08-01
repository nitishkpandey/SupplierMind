# SupplierMind — Evaluation, Results, and Findings

This document is written to be lifted directly into the dissertation's results
chapter. It explains the experimental setup, maps every evaluation metric to the
research question and hypothesis it tests, and for each metric gives four things
in plain language: **what it measures, how it was tested, the result, and what
the result means.**

All numbers come from running the benchmark on the 10,000-supplier corpus,
repeated **5 times** (the systems are slightly non-deterministic, so I repeat
and report the spread). Everything is reproducible with the scripts in
`thesis/scripts/`; the raw per-run outputs are in `thesis/results/10k/` and the
aggregated numbers in `thesis/results/10k/METRICS.json`.

---

## The research gap this project fills

Before the results, it is worth stating plainly what problem this project
addresses and why it needed addressing. The short version is this: **there was
no reproducible, honest, component-level evaluation of whether — and, crucially,
*why* — an agentic architecture beats simpler retrieval or single-prompt
approaches for multi-constraint, auditability-sensitive procurement supplier
discovery, and at what cost.** This project provides exactly that.

### The wider context

Two research areas touch this work, and neither one covers it.

The first is the evaluation of large-language-model agents. There is now a
healthy set of agent benchmarks — for software engineering, for open-domain
question answering, for generic tool use. These have taught the field a lot
about how to measure agent behaviour, but they target tasks that look nothing
like industrial procurement, and they mostly stop at an end-to-end score: "the
agent solved *N%* of the tasks." They rarely isolate *which part* of an agent is
responsible for its performance, and they almost never treat *auditability* — the
ability to trace an answer back to evidence — as something to be measured.

The second is the evaluation of retrieval-augmented generation (RAG). There are
good frameworks for judging whether a RAG system retrieves and answers well, but
they are generic: they are not built around the specific shape of a procurement
query, where several hard constraints (a certification, a minimum capacity, a
maximum lead time, a geography) must be satisfied *simultaneously*, and where the
buyer must be able to justify the choice to an auditor.

The task in between — finding suppliers under stacked hard constraints, with an
answer a procurement team can defend — is done in practice by keyword search plus
manual vetting, or increasingly by ad-hoc LLM tools. But it has **no standard,
public, reproducible benchmark**, and so no one has been able to answer the
obvious question rigorously: for this task, is an elaborate agentic system
actually better than a simple RAG pipeline, and if so, is it worth the cost?

### The specific gap, in four parts

Putting those observations together, four things did not exist together before
this work, and all four are needed to answer the question honestly.

1. **A constraint-grounded benchmark for multi-constraint procurement discovery.**
   Existing benchmarks are for coding or general QA. Supplier discovery under
   several stacked constraints, with exact structured ground truth, had not been
   benchmarked. I built one — SupplierBench-25 — with hand-verified correct
   answers per query, three difficulty tiers, and a deliberate five-query
   *abstention* set of impossible queries to test whether a system knows when to
   say "nothing qualifies."

2. **A controlled comparison that isolates the architecture from the model and
   the data.** Most comparisons in the literature change several things at once —
   a different model, a different corpus — so it is impossible to say whether a
   result is due to the architecture or the model. Here the model, the corpus,
   the ground truth, and the scoring code are held identical across all three
   paradigms, so any difference is attributable to the architecture alone.

3. **Component-level attribution, not just an end-to-end score.** Knowing *that*
   an agentic system wins is far less useful than knowing *which part* of it
   wins. Through an ablation I show that the advantage comes almost entirely from
   one component — the compliance / evidence gate — and that without it the
   agentic system actually falls *below* plain RAG. This kind of "why" finding is
   rare in applied agent work, which usually stops at the headline number.

4. **Auditability and verifiability treated as first-class, quantified metrics.**
   Procurement is a domain where a *defensible, evidence-linked* answer matters as
   much as a correct one. Rather than assert that the agentic system is more
   auditable, I measure it — with an auditability rubric, an evidence-link ratio,
   the accuracy of its per-constraint verdicts, its hallucination rate, and its
   behaviour on impossible queries.

### What this project contributes

Concretely, the contributions are:

- **A reusable, reproducible benchmark** (SupplierBench-25 plus the Abstention-5
  set) with structured ground truth, difficulty tiers, and released code.
- **A controlled three-paradigm comparison** (single-prompt vs RAG vs agentic)
  under identical model, corpus, and scoring, so the finding is about the
  architecture.
- **A component ablation** that localises the agentic advantage to the compliance
  gate — the single most useful "why" result in the thesis.
- **A quantified auditability and verifiability suite**, which connects the
  agentic architecture to a real governance requirement instead of a vague claim.
- **An honest account of the trade-off** — the cost, the latency, and one clean
  negative result (the agentic system refuses impossible queries *worse* than
  RAG) — which is what makes the whole evaluation credible.

### Why it matters, and the honest limits of the claim

For research, this offers a template for evaluating agentic architectures against
simpler baselines in a domain where auditability is not optional, with
mechanistic attribution rather than a black-box score. For practice, it gives
procurement teams evidence about *when* the agentic overhead is worth paying —
on hard, multi-constraint, audit-sensitive queries it clearly is; on simple
queries, or in cost- and latency-sensitive settings, it may not be.

I am deliberate about the size of this claim. This is a **seed benchmark** — 25
scored queries, a single annotator, a synthetic corpus — so it is best understood
as a rigorous, reproducible *case study*, not a universal statement about agents.
Its strength is internal validity and honesty: the same model and data
everywhere, an ablation to isolate cause, confidence intervals on every headline
number, and negative results reported rather than hidden. Extending it to a
larger, multi-annotator, real-world corpus, and confirming the findings on a
second model, are the natural next steps — and I flag them as such rather than
overreaching from what 25 queries can support.

---

## 1. Experimental setup

- **Systems under test.**
  - **P1 — single-prompt LLM:** the query goes straight to the model, which
    writes a list of supplier names from memory. No corpus, no retrieval.
  - **P2 — RAG:** the query is embedded, the ten most similar suppliers are
    retrieved from the vector index, and one prompt asks the model to pick five.
  - **P3 — SupplierMind:** the full five-agent system (Parser → Discovery →
    Compliance → Ranking → Evaluator) with tool use, constraint filtering,
    evidence-checked compliance, and auditable ranking.
- **Same everything else.** All three use the same model (OpenAI
  `gpt-4o-mini`), the same 10k corpus, the same ground-truth labels, and the
  same scoring code. So any difference in results is due to the architecture,
  not the model or the data.
- **Benchmark.** SupplierBench-25: 25 procurement queries across three
  difficulty tiers (simple / medium / hard), each with a hand-verified set of
  correct supplier IDs (at least three per query). Plus Abstention-5: five
  queries with no correct answer on purpose.
- **Repeats.** The full 25-query benchmark was run five times for all three
  systems. Metrics are reported as the mean over the five runs, with confidence
  intervals and a run-to-run stability check.
- **A note on the agentic system's clarifying questions.** P3 is designed to
  pause and ask the user a narrowing question when a query is under-specified.
  In an automated benchmark there is no user to answer, so P3 was run in
  "proceed anyway" mode: it answers every query with its best-effort
  understanding, and I separately record how often it *would* have asked (the
  clarification rate). This measures its retrieval quality on the same footing
  as the other systems while still reporting its questioning behaviour.

---

## 2. How the evaluations map to the research questions

Each research question has a hypothesis, and each hypothesis is tested by a
specific set of metrics. This table is the map; §4–§6 explain each metric.

| Research question | Hypothesis | Metrics that test it | Verdict |
|---|---|---|---|
| **RQ1** — How do the three architectures compare on satisfying multi-constraint queries? | **H1:** the agentic system satisfies more constraints correctly, and the gap widens as constraints stack | Precision@5, MRR, nDCG@5, MAP@5, Success@1, Recall@5, CSR, Harmonized CSR, Precision@5 by difficulty tier, paired significance test | **Supported** |
| **RQ2** — How does auditability (linking claims to evidence) compare? | **H2:** auditability is highest for the agentic system, lowest for single-prompt, RAG in between | Auditability rubric, Evidence-link ratio, Compliance-gate accuracy, Entity-hallucination rate, Correct-abstention rate | **Supported** (auditability clearly; but see §5.4 — the agentic system refuses *worse* than RAG on impossible queries) |
| **RQ3** — Which queries does each handle well, and where does each fail? | **H3:** single-prompt collapses on hard queries, RAG weakens on multi-constraint ones, the agentic system degrades most gracefully but pays in latency and cost | Precision@5 by tier (all systems), Answer rate, Clarification (ask) rate, Cost per query, Cost per correct supplier, Latency, Run-to-run variance, Abstention behaviour | **Supported** |

---

**Companion file.** Six further experiments that look *inside* the agentic
system — a component **ablation** (which part drives the advantage),
**intent-resolution** accuracy (how well the parser reads the query), an **error
taxonomy**, **tool-access** analysis, **prompt efficiency**, and **clean
latency** — are reported in `findings_diagnostics.md`. They are cross-referenced
from §4–§6 where relevant.

### 2.1 Why each metric was chosen (selection rationale)

A benchmarking thesis is only as credible as its choice of metrics, so this
section states *why* each metric earns its place — separately from §4–§6, which
explain what each one measures. The suite was not assembled by listing every
metric that exists; each was chosen to serve one of five deliberate principles.

1. **Paradigm-neutral fairness.** At least one headline number must be computed
   *identically* for all three systems, so that no architecture is scored on its
   own terms. This is why **Precision@5** is the primary headline (pure ID-vs-ID
   matching, no system-specific scorer) and why **Harmonized CSR** exists at all.
2. **Standard IR practice, for external credibility.** An examiner should
   recognise the measures as the field's canonical ones, not bespoke inventions.
   This is why **nDCG@5**, **MAP@5**, and **MRR** are included with their standard
   definitions and citations (Järvelin and Kekäläinen, 2002; Smucker et al., 2007).
3. **Procurement-domain fit.** Generic retrieval scores are not enough for a
   sourcing task, so the suite adds measures that speak to the *decision*:
   **CSR** (are the constraints actually met?), the **auditability rubric** and
   **compliance-gate accuracy** (is the answer defensible and are its verdicts
   true?), and **correct-abstention** (does it know when nothing qualifies?).
4. **Complementarity — no single metric decides the outcome.** Each metric has a
   blind spot; the suite is built so that another metric covers it. A conclusion
   that survives Precision@5, MRR, nDCG@5, MAP@5, *and* Success@1 is far harder to
   dismiss than one resting on a single figure.
5. **Honesty.** Some metrics are included precisely because they can make the
   agentic system look *worse* — **Recall@5**, **Harmonized CSR**, and
   **correct-abstention** — and reporting them is what makes the favourable
   results believable.

The table below gives the one-line justification for each metric: why it is in the
suite, and what the evaluation would be missing without it.

| Metric | Why it was selected (its job in the suite) | What would be missing without it |
|---|---|---|
| **Precision@5** | The one headline number computed identically for all three paradigms; k=5 matches how many candidates a buyer actually inspects | No fair, scorer-neutral headline — every other number could be accused of favouring one architecture |
| **MRR** | Procurement users read top-down; captures whether a *correct* supplier sits at the very top, which a set-based measure ignores | Cannot distinguish "correct but buried at rank 5" from "correct and first" |
| **nDCG@5** | The field's canonical rank-aware measure; rewards ordering and lends external credibility | An examiner would rightly ask why the standard ranking metric is absent |
| **MAP@5** | Single number that rewards finding *many* correct suppliers *and* finding them early; complements nDCG | No combined precision-across-ranks view |
| **Success@1** | Models the real "trust the top pick" user — the strictest practical test | Miss the most decision-relevant behaviour (what happens if the buyer takes only the first result) |
| **Recall@5** | Included for completeness and honesty, even though it is structurally low here; shows precision was not cherry-picked | Open to the charge of hiding poor coverage behind precision |
| **Answer rate** | Separates "returned the wrong suppliers" from "returned nothing", so precision cannot be inflated by silently skipping hard queries | High precision could be gamed by quiet abstention |
| **CSR (native)** | Answers the literal procurement question — do the returned suppliers meet the constraints? — using each system's own verdicts | No direct domain-level satisfaction measure |
| **Harmonized CSR** | Re-scores every system (P3 included) with one field-comparison scorer, removing self-scoring bias; the key fairness fix | The CSR comparison would be indefensible — P3 grading its own homework |
| **Auditability rubric** | Turns a governance property (traceability) into something measured, not asserted; directly operationalises RQ2 | RQ2 collapses into hand-waving |
| **Evidence-link ratio** | Quantitative complement to the coarse 0–3 rubric — the fraction of claims tied to a record | Rubric alone is too blunt to be convincing |
| **Compliance-gate accuracy** | Auditability is worthless if the recorded verdicts are wrong; validates the evidence trail is *trustworthy*, not merely present. The quantitative core of H2 | "Structured" would never be shown to equal "correct" |
| **Entity-hallucination rate** | Quantifies the exact failure mode grounding is meant to fix, and shows P2/P3 are immune by construction | The thesis's central motivation (hallucination) would go unmeasured |
| **Correct-abstention rate** | Tests "knowing when to say nothing", following the unanswerable-question method (Rajpurkar et al., 2018); surfaces the honest negative result | The one axis where P3 loses would be hidden |
| **Precision@5 by difficulty tier** | The direct test of H1's "gap widens as constraints stack" claim, and the clearest single picture of RQ3 | H1's mechanism claim would be untested |
| **Clarification (ask) rate** | Reports the genuinely agentic behaviour the other systems lack, and justifies "proceed-anyway" mode as the fair comparison setting | P3's questioning capability would be invisible |
| **Cost per query / per correct supplier** | The whole thesis question is "is the agentic overhead worth it?" — this is the cost side of that trade-off | No basis for the "when is it worth paying" recommendation |
| **Latency (pacing removed)** | Reports true compute cost, separated from the free-tier rate-limit artefact | The cost picture would be distorted by an infrastructure quirk |
| **Run-to-run variance** | Shows the results are reproducible despite the stochastic parser | A headline could be dismissed as a lucky run |
| **Paired significance test** | With only 25 queries a gap could be noise; the paired bootstrap (Smucker et al., 2007) tests that it is real | The headline P3 > P2 claim would not be defensible as statistically significant |
| **Component ablation** *(companion file)* | The mechanistic "why" — attributes the advantage to the compliance gate specifically; the single most distinctive result | The thesis would stop at "the agent won" rather than explaining *why* |

The short version: the retrieval-quality metrics establish *that* the agentic
system is better and are cross-checked against each other; the constraint,
auditability, and abstention metrics establish *whether the answer is defensible*,
which is the procurement-specific contribution; the cost and latency metrics price
the trade-off; and the significance test, variance, and ablation establish that
the result is real, reproducible, and mechanistically explained rather than
asserted.

## 3. Statistical treatment (how to read the numbers)

With only 25 queries this is a **seed benchmark**, so results are reported as
observed values, not population-scale claims. Two tools keep the reading honest:

- **95% bootstrap confidence interval (CI).** I resample the 25 queries with
  replacement many thousands of times and recompute the mean each time; the
  middle 95% of those means is the interval. Plainly: "if the query set had come
  out a bit differently, the average would very likely land in this range." A
  narrow interval means a stable estimate.
- **Paired bootstrap significance test.** To ask whether P3 really beats P2 (and
  it is not just luck), I take the per-query difference (P3 minus P2) on the
  same 25 queries and bootstrap the average difference. If the whole 95%
  interval sits above zero, the advantage is statistically significant.
- **Run-to-run variance.** Because the parser is slightly random, I also report
  the standard deviation across the five repeats. A small value means the result
  is reproducible.

---

## 4. RQ1 — Constraint satisfaction and retrieval quality

> **H1: the agentic system satisfies more constraints correctly, and the gap
> widens with more constraints. → Supported.**

### 4.1 Headline table

| Metric | P3 SupplierMind | P2 RAG | P1 single-prompt |
|---|---|---|---|
| **Precision@5** | **0.731** [0.619, 0.838] | 0.504 [0.352, 0.664] | 0.000 |
| **MRR** | **0.984** [0.952, 1.000] | 0.793 [0.633, 0.933] | 0.000 |
| **nDCG@5** | **0.795** | 0.559 | 0.000 |
| **MAP@5** | **0.731** | 0.490 | 0.000 |
| **Success@1** | **0.984** | 0.760 | 0.000 |
| **Recall@5** | 0.351 | 0.150 | 0.000 |
| **CSR (as-scored)** | 0.954 [0.931, 0.974] | 0.877 [0.806, 0.941] | 0.000 |
| **Harmonized CSR** | **0.934** [0.895, 0.964] | 0.917 [0.870, 0.960] | 0.000 |
| **Answer rate** | 0.984 | 1.000 | 0.000 |

### 4.2 Precision@5 (P@5)

- **What it measures.** Of the five suppliers a system returns, what fraction
  are genuinely correct for that query. This is the fairest headline number,
  because it is computed identically for all three systems (by matching returned
  supplier IDs against the ground-truth IDs).
- **How it was tested.** For each of the 25 queries, I took the top five
  returned IDs and counted how many were in that query's ground-truth set, then
  averaged over queries and over the five runs.
- **Result.** P3 **0.731**, P2 **0.504**, P1 **0.000**. In everyday terms: about
  3.7 of P3's top 5 are correct, versus about 2.5 for P2. P1 scores zero because
  the names it invents do not exist in the corpus.
- **What it means.** The agentic system retrieves markedly more correct
  suppliers than plain RAG. This is the central quantitative result of the
  thesis and the primary evidence for H1.

### 4.3 Mean Reciprocal Rank (MRR)

- **What it measures.** How near the top of the list the *first* correct
  supplier appears. If the first result is correct the score is 1; if the first
  correct one is in position two it is 0.5, and so on.
- **How it was tested.** For each query I found the rank of the first correct
  supplier and took its reciprocal, then averaged.
- **Result.** P3 **0.984**, P2 **0.793**, P1 **0.000**.
- **What it means.** P3 almost always puts a correct supplier in the very first
  position (0.984 ≈ "nearly always rank 1"). RAG usually does too, but less
  reliably. Good ranking matters because a procurement user looks at the top of
  the list first.

### 4.4 nDCG@5 and MAP@5

- **What they measure.** Two standard information-retrieval measures of *ranked*
  quality. **nDCG@5** rewards putting correct suppliers higher up (a correct
  result at rank 1 is worth more than at rank 5). **MAP@5** (mean average
  precision) rewards getting many correct results and getting them early.
- **How they were tested.** Computed from the ordered top-5 IDs against the
  ground-truth set, per query, averaged over queries and runs.
- **Result.** nDCG@5: P3 **0.795** vs P2 0.559. MAP@5: P3 **0.731** vs P2 0.490.
- **What it means.** These confirm the P@5 story from a ranking angle: P3 does
  not just find more correct suppliers, it orders them better. Reporting both is
  standard practice and strengthens the claim beyond a single metric.

### 4.5 Success@1

- **What it measures.** Whether the single top result is correct — the strictest
  "did you get it right immediately" test.
- **How it was tested.** Scored 1 if the first returned supplier is in the
  ground truth, else 0; averaged.
- **Result.** P3 **0.984**, P2 **0.760**, P1 0.000.
- **What it means.** P3's first suggestion is almost always right; RAG's is
  right about three times in four. For a user who trusts the top pick, that is a
  large practical difference.

### 4.6 Recall@5

- **What it measures.** Of *all* the correct suppliers that exist for a query,
  how many appear in the top five.
- **How it was tested.** Number of correct IDs found in the top five divided by
  the total number of correct IDs for that query.
- **Result.** P3 **0.351**, P2 0.150.
- **What it means (important caveat).** Recall looks low for everyone, and this
  is expected: on the 10k corpus a simple query like "metals suppliers in
  Germany" has more than a hundred correct answers, so five slots can only ever
  cover a small fraction. Recall is therefore **not the metric to lean on** on
  this benchmark — precision is. It is reported for completeness, and P3 still
  finds twice as many correct suppliers as RAG.

### 4.7 Constraint Satisfaction Rate (CSR) and Harmonized CSR

- **What it measures.** CSR asks the core procurement question directly: do the
  returned suppliers actually meet the query's constraints (certification,
  capacity, lead time, location)? It scores each returned supplier on how many
  of the query's constraints it satisfies (a partial match counts as a half),
  then averages.
- **The subtlety, and why "harmonized" exists.** P3 produces its own
  per-constraint verdicts, so its CSR can be read straight from its compliance
  output. P1 and P2 have no such verdicts, so their CSR is computed by comparing
  supplier fields to the query. Those are two different scorers, which is not a
  fair comparison. **Harmonized CSR** fixes this by re-scoring *every* system —
  including P3 — with the same field-comparison scorer.
- **How it was tested.** As-scored CSR uses each system's native method;
  harmonized CSR re-runs P3's returned suppliers through the same profile-based
  scorer used for P1 and P2.
- **Result.** As-scored: P3 **0.954** vs P2 0.877. Harmonized (apples-to-apples):
  P3 **0.934** vs P2 **0.917**.
- **What it means.** On a strictly like-for-like scorer, P3 still satisfies more
  constraints than RAG, but the margin is small (about 2 points). The honest
  reading is that **the large, reliable win is on precision and ranking (§4.2–
  4.5), while on raw constraint-counting the two are close.** Reporting the
  harmonized number is what makes the CSR comparison defensible.

### 4.8 Answer rate

- **What it measures.** How often a system returns anything at all. This
  separates "returned the wrong suppliers" from "returned nothing", which a
  single quality score would otherwise hide.
- **How it was tested.** Fraction of queries with a non-empty result list.
- **Result.** P3 **0.984**, P2 **1.000**, P1 0.000.
- **What it means.** In "proceed anyway" mode P3 answers essentially every
  query, so its high precision is not achieved by quietly skipping hard cases.
  (In an earlier, flawed setup P3 was recorded as returning nothing on many
  queries — that was a scoring artifact, now removed; see §7.)

### 4.9 The key H1 evidence — the gap widens with difficulty

Precision@5 broken down by difficulty tier:

| Tier | P3 | P2 | P1 |
|---|---|---|---|
| Simple | 0.950 | 0.950 | 0.000 |
| Medium | 0.664 | 0.340 | 0.000 |
| Hard | 0.577 | 0.229 | 0.000 |

- **How it was tested.** The same Precision@5, averaged within each difficulty
  tier separately.
- **Result & meaning.** On simple queries P3 and P2 are level. As constraints
  stack, P3 pulls away: on medium queries it is twice as precise, on hard
  queries about two-and-a-half times. **This widening gap is exactly what H1
  predicted** — the agentic machinery earns its keep precisely when the query is
  hard. It is also the clearest single picture of RQ3: RAG degrades much faster
  than the agentic system as difficulty rises.

### 4.10 Is the P3 > P2 gap real? (significance test)

- **What it is.** A paired bootstrap test on the per-query Precision@5
  difference (P3 minus P2), to check the advantage is not just noise.
- **How it was tested.** For each of the 25 queries I computed P3's mean P@5
  minus P2's mean P@5, then bootstrapped the average difference (see §3).
- **Result.** Mean difference **+0.227**, 95% CI **[0.126, 0.330]**, bootstrap
  **p ≈ 0.000**. The entire interval sits above zero.
- **What it means.** P3's precision advantage over RAG is **statistically
  significant**, not a fluke of which queries happened to be chosen. Combined
  with the tiny run-to-run variance (P3 P@5 standard deviation ≈ 0.03; P2 is
  fully deterministic), the result is both real and reproducible.

---

## 5. RQ2 — Auditability, verifiability, and trust

> **H2: auditability is highest for the agentic system, lowest for
> single-prompt. → Supported.**

### 5.1 Auditability rubric (0–3) and evidence-link ratio

- **What they measure.** The rubric scores the *form* of each system's output:
  0 = plain prose with no structure; 1 = structured but suggestions not linked
  to evidence; 2 = suggestions linked to evidence; 3 = suggestions linked to
  evidence **and** the full reasoning chain recorded in a queryable log. The
  evidence-link ratio is the fraction of a system's supplier claims that point
  back to a specific record.
- **How it was tested.** By inspecting representative outputs and the audit log
  each system produces.
- **Result.** Rubric: **P3 = 3, P2 = 1, P1 = 0.** Evidence-link ratio: P3 1.0,
  P2 1.0, P1 0.0.
- **What it means.** P1 offers no traceability at all (prose from memory). P2 is
  grounded in real retrieved records but records no per-constraint reasoning.
  Only P3 links every suggestion to evidence and keeps a full, queryable audit
  trail — the structural basis of H2.

### 5.2 Compliance-gate accuracy (the quantitative core of H2)

- **What it measures.** Auditability is only worth something if the recorded
  judgments are *correct*. This metric treats P3's per-constraint PASS/FAIL
  verdicts as predictions and checks them against the truth in the corpus —
  effectively asking "when P3 says a supplier meets a constraint, is that
  true?".
- **How it was tested.** For every supplier P3 returned and every constraint it
  judged, I compared its verdict to the actual field in the corpus, pooled
  across all five runs (about 1,500 verdicts), and computed accuracy plus the
  precision and recall of its PASS decisions.
- **Result.** Accuracy **0.995**; PASS-verdict precision **0.994**, recall
  **1.000**.
- **What it means.** P3's compliance claims are almost always true, and it never
  missed a genuinely qualifying supplier (recall 1.0). So its evidence trail is
  trustworthy, not merely present — this is what turns "P3 is structured" into
  "P3 is verifiable."

### 5.3 Entity-hallucination rate

- **What it measures.** Whether a system returns suppliers that do not exist.
- **How it was tested.** For P1 I checked whether each supplier name it emitted
  matches any real supplier in the corpus (after normalising for spacing/case).
  P2 and P3 can only return real corpus IDs, so they cannot hallucinate an
  entity by construction.
- **Result.** **P1 = 1.000** (every name it produced was invented); P2 and P3
  ≈ 0.
- **What it means.** The pure-parametric baseline hallucinates a non-existent
  supplier on every single query — a clean, striking illustration of why
  grounding matters. Retrieval (P2) and the agentic system (P3) are immune to
  this failure mode.

### 5.4 Correct-abstention rate (Abstention-5) — an honest negative result

- **What it measures.** On the five queries that have *no* correct answer, does
  the system correctly return nothing instead of presenting a supplier that does
  not actually qualify?
- **How it was tested.** The five unsatisfiable queries were run through all
  three systems (one run, five queries — small, so read as indicative). I
  measured how often each returned an empty result (correct abstention) versus
  returning or inventing a supplier (a hallucinated match).
- **Result.**

  | System | Correct-abstention | Hallucination |
  |---|---|---|
  | P2 RAG | **0.80** | 0.20 |
  | P3 SupplierMind | 0.40 | 0.60 |
  | P1 single-prompt | 0.00 | 1.00 |

- **What it means (and it is not what one might expect).** This is the one axis
  where the agentic system does **not** win, and reporting it plainly is part of
  the thesis's honesty. As expected, single-prompt invents a supplier every time
  (100% hallucination). But RAG's simple prompt often *declines* to pick
  mismatched suppliers, so it correctly returns nothing on four of the five
  queries. The agentic system, by contrast, returns near-misses on three of the
  five: its ranking layer surfaces the closest partial matches (for example,
  German logistics firms that lack the required AS9100 certificate) rather than
  returning an empty list.
- **The nuance that keeps this useful.** P3's near-misses are returned *together
  with their failing-constraint verdicts*, so a user can see at a glance that
  they do not fully qualify — which in real procurement is often more useful than
  a blank result. So the picture is: P3 does not *refuse* well, but it does not
  *deceive* either — it shows auditable near-misses. Measured strictly as
  "correct refusal," though, P3 under-performs RAG here.
- **Concrete improvement this points to.** Add a hard-abstain threshold to the
  ranking layer: when no candidate passes all hard constraints, return an empty
  list (or an explicit "no full match; closest near-misses below"). This is a
  small, well-motivated change flagged directly by the experiment.
- **Caveat.** Five queries, one run — treat as indicative, not definitive.

---

### 5.5 Does a clearer query stop P1 hallucinating? (a targeted probe)

- **What it evaluates.** The headline result — that single-prompt P1 hallucinates
  on 100% of queries (§5.3) — invites a fair objection: perhaps that is only
  because the benchmark queries are short. Would a very clear, fully-specified
  query let the parametric model return real, usable suppliers? This probe tests
  exactly that objection.
- **Why it matters.** If clarity fixed P1, the single-prompt approach might still
  be salvageable for well-worded, easy requests. If it does not, then the
  hallucination is *structural* — a consequence of having no corpus — and the
  case for grounding (retrieval or the agentic pipeline) is even stronger.
- **How it was tested.** I ran P1 on maximally curated queries: fully specified
  (category, certification, country, capacity, lead time) and even *instructing
  the model to return "exact, real company names."* I then checked every returned
  name against the 10k corpus. This is reproducible with
  `thesis/scripts/probe_p1_curated.py` (one LLM call per query, no databases).
- **Result.** Two representative examples:

  *Query 1:* "Find five ISO 9001 certified metal suppliers in Germany with
  capacity above 10,000 kg/month and lead time under 30 days. Give exact, real
  company names." → **Thyssenkrupp AG, Salzgitter AG, Friedrich Kocks GmbH & Co.
  KG, Krupp Edelstahlprofile GmbH, Hüttenes-Albertus Chemische Werke GmbH.**
  Corpus matches: **0/5**.

  *Query 2:* "List five ISO 22000 certified food ingredient suppliers in Germany.
  Return only exact, real company names." → **BASF SE, Kerry Group, Südzucker AG,
  Wacker Chemie AG, Döhler GmbH.** Corpus matches: **0/5**.

  In both cases the hallucination rate is **100%**, unchanged from the terser
  benchmark queries.

- **What it means — and an important nuance.** A clearer query does not help P1
  at all: it still returns zero corpus matches. But the reason is subtle and
  worth stating precisely. P1 is **not inventing fictional companies** — it is
  recalling *genuinely real* German firms (Thyssenkrupp, BASF, Südzucker) from
  its training data. The problem is that these real companies are **not in the
  private corpus the benchmark scores against.** So "hallucination" here means
  "not grounded in the database I am searching," which covers two failure modes
  at once: fabricated names, and real names that are simply absent from the
  target corpus. For this benchmark — and, crucially, for any real deployment
  against a specific buyer's approved-supplier database — both are equally
  useless: the model cannot know which suppliers are actually *in the database*,
  so it cannot return verifiable, in-database results no matter how well the query
  is phrased.
- **The takeaway.** P1's hallucination is **structural, not a clarity problem.**
  It follows directly from having no access to the corpus, and better prompting
  cannot fix it. This makes the case for grounding stronger, not weaker: the only
  remedies are retrieval (P2) or the agentic pipeline (P3), both of which can only
  ever return real corpus suppliers by construction.

## 6. RQ3 — Where each system wins, fails, and what it costs

> **H3: single-prompt collapses on hard queries; RAG weakens on multi-constraint
> ones; the agentic system degrades most gracefully but pays in latency and
> cost. → Supported.**

### 6.1 Graceful degradation

The per-tier table in §4.9 is the primary evidence here. In summary: P1 is at
zero throughout (it cannot use the corpus); P2 starts strong on simple queries
(0.95) but falls steeply to 0.23 on hard ones; P3 falls much more gently (0.98 →
0.68 → 0.57). The agentic system degrades most gracefully as difficulty rises —
exactly the H3 prediction.

### 6.2 Clarification (ask) rate

- **What it measures.** How often the agentic system *wanted* to pause and ask
  the user a narrowing question, broken down by difficulty.
- **How it was tested.** In "proceed anyway" mode (see §1) I recorded, for each
  query, whether P3 would have raised a clarification, then aggregated by tier.
- **Result.** Overall **0.34**; by tier: **simple 38/40, medium 5/50, hard
  0/35** (across the 5 runs × queries per tier).
- **What it means.** The agentic system wants to clarify almost every
  **under-specified** simple query (e.g. "metals suppliers in Germany" — too
  broad) and **never** a fully-specified hard one. This is precisely the
  behaviour a careful procurement assistant should show, and it is a genuinely
  agentic capability the other two systems lack. It also explains why forcing
  P3 to proceed is the fair way to compare retrieval quality.

### 6.3 Cost per query and cost per correct supplier

- **What they measure.** The money each system spends per query, and — dividing
  by how much it gets right — the money per correct supplier returned.
- **How it was tested.** Summed the logged LLM spend attributed to each query;
  cost-per-correct = cost per query ÷ (Precision@5 × 5).
- **Result.** Cost/query: P3 **$0.00140**, P2 $0.00030, P1 $0.00020. Cost per
  correct supplier: P3 **$0.00038**, P2 $0.00012.
- **What it means.** The agentic system costs about **4.7× more per query** than
  RAG, because it makes roughly six sequential LLM calls versus RAG's one. Even
  after adjusting for its higher accuracy (cost-per-correct), it is about 3×
  more expensive. This is the clearest, cleanest *cost* of the agentic
  approach — a real and quantified trade-off.

### 6.4 Latency

- **What it measures.** True compute time per query, separated from the delay
  caused by the embedding provider's free-tier rate limit.
- **How it was tested.** The raw wall-clock time is badly distorted by the free
  embedding tier (3 requests/minute), which forces ~40-second pacing sleeps at
  random points. So the rate limiter now records exactly how long it slept, and
  I subtract that per-query pacing time from the wall-clock time to get real
  compute time. (Full breakdown in `findings_diagnostics.md` §6.)
- **Result (compute time, pacing removed).** P3 ≈ **13.2 s**, P2 ≈ **2.8 s**,
  P1 ≈ 3.5 s. For reference, P3's raw wall-clock was ~21 s, of which ~8 s was
  pure provider-pacing wait.
- **What it means.** Even after removing the free-tier delay, the agentic system
  is about **4.7× slower** than RAG — it makes ~5 LLM calls per query versus one.
  This is the second real cost of the approach, alongside the ~4.7× dollar cost
  (§6.3), and it completes the H3 picture: the agentic system is more accurate
  and more auditable, but heavier.

### 6.5 Run-to-run variance (reproducibility)

- **What it measures.** How much each headline number moves across the five
  repeats — a check that the results are stable, given the parser is slightly
  random.
- **How it was tested.** Standard deviation of each system's metric across the
  five runs (`aggregate_variance.py`).
- **Result.** P3's Precision@5 standard deviation ≈ **0.03**; P2 is fully
  deterministic (0.00).
- **What it means.** The agentic system's small randomness does not
  meaningfully move its scores — the findings are reproducible, not a lucky run.

---

## 7. Tradeoffs, limitations, and honesty notes

- **Cost and latency are the price of quality.** P3 wins on accuracy,
  auditability, and graceful degradation, but costs ~4.7× more and runs several
  times slower. The thesis conclusion is not "agentic is strictly better" but
  "agentic is more accurate and more trustworthy, at a measurable cost."
- **The earlier 'agentic loses' result was an artifact.** A previous run on the
  small 100-supplier corpus, with a scoring rule that gave P3 a zero whenever it
  asked a clarifying question, made P3 look worse than RAG. Both problems are
  fixed here (10k corpus with satisfiable queries; proceed-anyway scoring with
  the ask-rate reported separately). This is documented rather than hidden.
- **Recall is weak on this benchmark by design** (high-prevalence simple
  queries); precision is the metric to trust here.
- **On a strict like-for-like scorer, the CSR gap is small** — the durable win
  is precision and ranking, not raw constraint-counting.
- **Parser text can be messy, but the structured extraction is not brittle.**
  An earlier informal read of the logs suggested the parser was fragile. The
  intent-resolution experiment (`findings_diagnostics.md` §2) corrects this: the
  parser extracts the structured constraints that drive retrieval **99.3%**
  correctly. The messiness is confined to a free-text product field that
  retrieval does not use (a ~17% "polluted product string" rate,
  `findings_diagnostics.md` §3), so it is cosmetic. The genuinely harmful
  failures (a real parse failure, a missed constraint) occur ≤3% of the time.
- **The agentic system does not refuse well (negative result).** On
  unsatisfiable queries it returns near-misses (60% of the time) rather than an
  empty list, doing worse than RAG on correct abstention (§5.4). Its near-misses
  are auditable (failing constraints shown), and a hard-abstain threshold on the
  ranking layer would fix it — but as it stands this is a real weakness, not to
  be glossed over.
- **Attribute-hallucination could not fire** on this clean synthetic corpus
  (compliance resolves deterministically, so there is nothing to fabricate);
  gate accuracy (0.995) is the real faithfulness number.
- **Scope.** 25 queries, one annotator, a synthetic corpus. Results are observed
  values with per-tier breakdowns and confidence intervals, not population
  claims. A cross-model check (the proposal's used Groq, since removed) is left
  as future work.

---

## 8. Positioning: why not just use a general-purpose LLM?

A fair and obvious challenge is this: *modern general-purpose LLMs — ChatGPT,
Perplexity, and similar tools, especially with web search — can already list
suppliers with links. So why build a five-agent system at all?* This section
answers that challenge directly, because it is the question the system most needs
to survive.

### The honest concession

I will not argue that my system *finds* supplier names better than a
search-enabled LLM. On the narrow task of "produce a plausible list of supplier
names, maybe with links," a general LLM does that well, and that capability is now
commoditised. Pretending otherwise would be indefensible. The probe in §5.5 even
shows that a plain LLM readily returns *real* company names (Thyssenkrupp, BASF)
from memory.

But that is exactly the point: **a name is not a procurement decision.** The
question is not "can a chatbot name a supplier?" (yes), but "can a chatbot be
trusted as a procurement discovery *system*?" (no) — and the difference is
everything that turns a name into something a buyer can act on. Discovery in
procurement is not a naming problem; it is a **trust-and-governance** problem.

### What the system provides that a general LLM cannot

Each of the following is a hard procurement requirement, not a convenience:

1. **It searches the buyer's own governed data first.** A general LLM has no
   access to a company's approved-supplier list, prior contracts, or vetted
   records — and, for confidentiality and data-protection reasons, that internal
   data usually *cannot* be sent to a third-party chatbot. Procurement decisions
   are made against the organisation's own governed corpus (the three-tier
   scope: approved → personally saved → pending review), not the open web.

2. **It verifies constraints against evidence instead of asserting them.** A
   chatbot will fluently state "this supplier is ISO 9001 certified with a 30-day
   lead time" whether or not it is true. The system's compliance gate checks each
   constraint against quoted evidence, or fails. This is not a stylistic
   preference: the ablation in `findings_diagnostics.md` §1 shows that removing
   this gate drops the system *below* plain RAG. So the value is demonstrably not
   the model picking a name — it is the verification wrapped around it.

3. **Sanctions and location are hard, deterministic gates.** Before a
   web-discovered supplier can enter a result, the system screens it against a
   real sanctions dataset (OpenSanctions) and validates a real city, country, and
   coordinates (Geoapify), then holds it for human approval. A general LLM will
   happily suggest a sanctioned entity or a fabricated address. Onboarding a
   sanctioned supplier is a legal and financial catastrophe, and that risk alone
   justifies a controlled pipeline rather than a chat window.

4. **Every decision is auditable.** Procurement is regulated and audited. The
   system writes a per-decision trail — which agent decided what, on what
   evidence, with what reasoning — so a supplier choice that is later challenged
   can be justified from a record. A chatbot produces a conversation transcript,
   not a queryable, per-constraint audit log tied to the buyer's data.

5. **It is controllable, reproducible, and private.** I can pin the model, replay
   a decision, and enforce hard business rules (for example, "never surface a
   supplier without a validated address"). A hosted consumer LLM changes
   underneath the user, cannot be pinned for reproducibility, and offers no place
   to insert deterministic policy — and sending confidential procurement data to
   it is often not permissible.

### The obvious rebuttal, answered

Someone will ask: *"Could you not just prompt ChatGPT to cite sources and check
sanctions?"* Prompting for a behaviour is not the same as guaranteeing it. Asking
a probabilistic model to "check sanctions" simply produces another fluent,
unverified sentence. My system enforces it as a hard, deterministic control
against an actual sanctions dataset and an actual geocoder, with human sign-off.
The difference is a capability **enforced by architecture** versus one
**requested by prompt** — and in a compliance setting only the former is
defensible.

### The framing that makes this coherent

The LLM is a **component inside my system, not a competitor to it.** The system
uses an LLM as its reasoning engine and wraps it with grounding in governed data,
per-constraint verification, sanctions and location gating, and an audit trail —
so the output becomes trustworthy and actionable in a regulated purchasing
process. The LLM is the engine; the contribution of this work is the brakes, the
seatbelts, and the logbook that make it safe to drive.

### An honest limit of this argument

Two caveats keep this defensible rather than overstated. First, on the raw
web-search step alone, the gap between my system and a modern search-enabled LLM
is genuinely small; my differentiation is deliberately the governance layer, and
I state that plainly rather than overclaim on retrieval. Second, the benchmark in
this thesis runs the system in *internal-only* mode (web discovery switched off
for reproducibility), so the sanctions, location, and audit advantages above are
demonstrated **architecturally rather than empirically measured here.** Building
a dedicated web-discovery experiment — comparing a plain LLM's unverified names
against the system's source-, location-, and sanctions-verified discoveries — is
the clearest way to turn this positioning argument into measured evidence, and I
flag it as the most valuable next experiment.

## 9. How to reproduce

Free, deterministic (no API keys, no cost):

```bash
python thesis/scripts/build_benchmark_10k.py      # build + verify the benchmark
python thesis/scripts/compute_all_metrics.py      # headline suite → METRICS.json
python thesis/scripts/analyze_diagnostics.py      # intent res / errors / tools / efficiency / latency
python thesis/scripts/analyze_ablation.py         # component ablation ladder
python thesis/scripts/aggregate_variance.py       # run-to-run stability
python thesis/scripts/analyze_abstention.py       # abstention scoring
```

Paid / needs infrastructure (Docker + API keys):

```bash
docker compose -f infra/docker/docker-compose.yml up -d
cd apps/backend
uv run python ../../thesis/scripts/verify_milvus_10k.py       # index health check
uv run python ../../thesis/scripts/run_10k_benchmark.py --p1 --p2 --p3 --runs 5   # main (instrumented)
uv run python ../../thesis/scripts/run_10k_benchmark.py --p3 --ablation no_compliance --runs 3
uv run python ../../thesis/scripts/run_10k_benchmark.py --p1 --p2 --p3 --abstention
```

The embedding provider's free tier is auto-paced to 3 requests/minute by the
rate limiter, so runs are stable but slow (~15–25 min each). No payment method
is required.
