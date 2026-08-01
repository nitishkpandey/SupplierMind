# Chapter 5: Evaluation and Results

This chapter reports the empirical study. It first describes the experimental
setup — the datasets, the baselines, the metrics, and the conditions under which
everything was run — and then presents the results systematically: the headline
comparison of the three paradigms, the breakdown by difficulty, the constraint,
auditability, and hallucination findings, the abstention result, the component
ablation, and a set of diagnostic analyses that look inside the agentic system.
Each section interprets its results in relation to the research questions, and the
chapter closes by answering RQ1 to RQ3 directly.

## 5.1 Experimental setup

**Datasets.** All experiments use SupplierBench-25 — twenty-five multi-constraint
procurement queries across three difficulty tiers (eight simple, ten medium, seven
hard) — over the ten-thousand-supplier synthetic corpus, together with the
five-query abstention set of intentionally unsatisfiable requests. Ground truth is
the exact set of suppliers satisfying each query's constraints, verified to contain
at least three suppliers per satisfiable query (Chapter 4).

**Baselines.** The single-prompt LLM (P1) and the RAG pipeline (P2) are the
baselines against which the agentic system (P3) is compared. P2 is the more
demanding baseline, since it is the dominant pattern in current procurement-AI
products and shares its retrieval stack with P3.

**Conditions.** All three paradigms run on the same pinned language model
(`gpt-4o-mini-2024-07-18`), the same corpus, the same ground truth, and the same
scoring code, so that differences are attributable to the architecture. Because the
parser is mildly stochastic, the full benchmark was run **five times**; reported
values are the mean over the five runs, with 95% bootstrap confidence intervals over
the queries. The agentic system was run in the non-interactive "proceed anyway"
mode, with its would-have-clarified rate recorded separately. The component ablation
was run three times.

**Metrics.** Results are reported across four families: retrieval quality
(Precision@5, MRR, nDCG@5, MAP@5, Success@1, Recall@5, answer rate); constraint
satisfaction (native and harmonised CSR); trust and auditability (auditability
rubric, evidence-link ratio, compliance-gate accuracy, entity-hallucination rate,
correct-abstention rate); and operational performance (cost per query, cost per
correct supplier, and latency). Definitions and formulas are given in Chapter 2 and
Section 4.5.

**Why this suite, and not one number.** The metrics were not accumulated for their
own sake; each serves one of five deliberate purposes, and stating them makes the
comparison defensible rather than arbitrary. The first is *paradigm-neutral
fairness*: at least one headline measure must be computed identically for all three
systems, which is why Precision@5 — pure identifier-against-identifier matching, with
no system-specific scorer — is the primary headline, and why the harmonised CSR
exists at all. The second is *standard practice*: nDCG@5, MAP@5, and MRR are the
information-retrieval field's canonical rank-aware measures (Järvelin and Kekäläinen,
2002), so the results can be recognised and trusted rather than taken on faith. The
third is *fit to the procurement decision*: generic retrieval scores are not enough
for a sourcing task, so the suite adds measures that speak to whether the answer is
usable and defensible — constraint satisfaction, the auditability rubric,
compliance-gate accuracy, and correct abstention. The fourth is *complementarity*:
every metric has a blind spot — Precision@5 ignores rank order, MRR ignores everything
after the first hit, recall is structurally low here — so the suite is built so that
another measure covers each gap, and a conclusion that survives all of them is far
harder to dismiss than one resting on a single figure. The fifth is *honesty*: some
measures are included precisely because they can make the agentic system look worse —
Recall@5, harmonised CSR, and the correct-abstention rate — and reporting them is what
lends credibility to the favourable results. Every reported difference is
additionally accompanied by a 95% bootstrap confidence interval and, for the headline
comparison, a paired significance test, so that a difference is only claimed when it
is statistically real rather than an artefact of which queries happened to be chosen.

## 5.2 Headline comparison (RQ1)

Table 5.1 reports the headline metrics for the three paradigms. The agentic system
is the strongest on every retrieval-quality measure, and the single-prompt baseline
scores zero throughout because the supplier names it produces do not exist in the
corpus.

| Metric | P3 SupplierMind | P2 RAG | P1 single-prompt |
|---|---|---|---|
| Precision@5 | **0.731** [0.619, 0.838] | 0.504 [0.352, 0.664] | 0.000 |
| MRR | **0.984** [0.952, 1.000] | 0.793 [0.633, 0.933] | 0.000 |
| nDCG@5 | **0.795** | 0.559 | 0.000 |
| MAP@5 | **0.731** | 0.490 | 0.000 |
| Success@1 | **0.984** | 0.760 | 0.000 |
| Recall@5 | 0.351 | 0.150 | 0.000 |
| CSR (native) | 0.954 [0.931, 0.974] | 0.877 [0.806, 0.941] | 0.000 |
| CSR (harmonised) | **0.934** [0.895, 0.964] | 0.917 [0.870, 0.960] | 0.000 |
| Answer rate | 0.984 | 1.000 | 0.000 |

*Table 5.1 — Headline metrics, mean over five runs, with 95% bootstrap confidence
intervals where shown.*

![Precision@5 by architecture: P3 SupplierMind 0.731, P2 RAG 0.504, P1 single-prompt 0.000, with 95% bootstrap confidence-interval error bars.](figures/figure_5_1_precision_by_paradigm.png)

*Figure 5.1 — Precision@5 by architecture, mean of five runs with 95% bootstrap
confidence intervals. A vector version for print is in
`figures/figure_5_1_precision_by_paradigm.pdf`.*

On Precision@5 — the fairest headline measure, since it is computed identically for
all systems — the agentic system reaches 0.731 against RAG's 0.504. To test whether
this difference is real rather than a product of which queries happened to be
chosen, a paired bootstrap test was run on the per-query Precision@5 differences
(P3 minus P2). The mean difference is **+0.227**, with a 95% confidence interval of
**[0.126, 0.330]**, and a bootstrap p-value of approximately 0.000. Because the
entire interval lies above zero, the advantage is statistically significant. It is
also reproducible: the run-to-run standard deviation of the agentic system's
Precision@5 is about 0.031, while the RAG pipeline is deterministic (0.000). The
ranking measures tell the same story from a ranking angle — the agentic system
places a correct supplier first on almost every query (Success@1 of 0.984) — and the
recall figures are low for both systems by construction, because a simple query on
this corpus can have more than a hundred correct answers, so five slots cannot cover
many of them; this is why precision, not recall, is the measure to rely on here.

The two CSR figures deserve comment. The agentic system's native CSR (0.954) exceeds
RAG's (0.877), but the native figure is read from the system's own verdicts. Under
the harmonised scorer, which scores every system identically, the gap narrows to
0.934 against 0.917. The honest reading is therefore that the large, reliable
advantage is in precision and ranking, while on raw constraint counting the two
systems are close — a distinction returned to in Section 5.9.

## 5.3 Degradation by difficulty (RQ1 and RQ3)

The mechanism behind the headline result becomes visible when Precision@5 is broken
down by difficulty tier (Table 5.2). On simple queries the two systems are level; as
constraints stack, the agentic system pulls away, roughly doubling RAG's precision on
medium queries and reaching about two and a half times its precision on hard ones.

| Tier | P3 | P2 | P1 |
|---|---|---|---|
| Simple | 0.950 | 0.950 | 0.000 |
| Medium | 0.664 | 0.340 | 0.000 |
| Hard | 0.577 | 0.229 | 0.000 |

*Table 5.2 — Precision@5 by difficulty tier.*

![Grouped bar chart of Precision@5 by difficulty tier: P3 and P2 level on simple queries (0.95 each), diverging to 0.664 vs 0.340 on medium and 0.577 vs 0.229 on hard.](figures/figure_5_2_precision_by_tier.png)

*Figure 5.2 — Precision@5 by difficulty tier for the agentic system (P3) and RAG
(P2), mean of five runs. The gap is negligible on simple queries and widens as
constraints stack — the visual evidence for H1. Vector version in
`figures/figure_5_2_precision_by_tier.pdf`.*

This widening gap is exactly what hypothesis H1 predicted: the agentic machinery
earns its keep precisely where the query is hard. It is also the clearest single
picture of RQ3 — the RAG pipeline degrades much faster than the agentic system as
difficulty rises, while the single-prompt baseline is flat at zero because it cannot
use the corpus at all.

## 5.4 Auditability, verifiability, and hallucination (RQ2)

Table 5.3 reports the trust measures. The auditability rubric and the evidence-link
ratio are structural properties of each architecture: the single-prompt baseline
produces unstructured prose with no evidence; RAG grounds its answers in real
retrieved records but records no per-constraint reasoning; only the agentic system
links every suggestion to evidence and keeps a queryable reasoning log.

| Signal | P3 | P2 | P1 |
|---|---|---|---|
| Auditability rubric (0–3) | 3 | 1 | 0 |
| Evidence-link ratio | 1.0 | 1.0 | 0.0 |
| Compliance-gate accuracy | 0.995 (PASS precision 0.994, recall 1.000) | — | — |
| Entity-hallucination rate | ~0 | ~0 | 1.000 |

*Table 5.3 — Auditability, verifiability, and hallucination.*

Two results stand out. First, the agentic system's compliance-gate accuracy is
0.995: when it judges a constraint, that judgement is true against the corpus 99.5%
of the time, with a PASS-verdict precision of 0.994 and a recall of 1.000. This
matters because auditability is only valuable if the recorded judgements are
correct; the agentic system's evidence trail is therefore trustworthy, not merely
present. Second, the single-prompt baseline hallucinates a non-existent supplier on
every query (a rate of 1.000). A targeted probe confirmed that this does not improve
when the query is made maximally clear: on fully specified queries that even
instructed the model to return "exact, real company names", the single-prompt
baseline still returned zero corpus matches, because it recalls real-world companies
from its training data that are simply not in the target corpus. The hallucination is
structural, a consequence of having no access to the corpus, and cannot be fixed by
better prompting. The retrieval and agentic systems are immune to this failure mode
by construction, since they can only return real corpus suppliers. Together these
findings support hypothesis H2: auditability and verifiability are highest for the
agentic system, lowest for the single-prompt approach, with RAG in between.

## 5.5 Abstention: an honest negative result (RQ2 and RQ3)

On the five unsatisfiable abstention queries, the picture reverses, and it is
reported here rather than omitted. Table 5.4 shows how often each system correctly
returned nothing.

| System | Correct-abstention rate | Hallucination (returned a non-qualifying supplier) |
|---|---|---|
| P2 RAG | 0.80 | 0.20 |
| P3 SupplierMind | 0.40 | 0.60 |
| P1 single-prompt | 0.00 | 1.00 |

*Table 5.4 — Behaviour on impossible queries (five queries, single run; indicative).*

This is the one axis on which the agentic system does not win. As expected, the
single-prompt baseline invents a supplier every time. But the RAG pipeline's prompt
often declines to select mismatched suppliers, so it correctly returns nothing on
four of the five queries, whereas the agentic system returns near-misses on three of
the five: its ranking layer surfaces the closest partial matches rather than an empty
list. The nuance that keeps this useful is that the agentic system's near-misses are
returned together with their failing-constraint verdicts, so a user can see that they
do not fully qualify — it does not deceive, but it does not refuse well either.
Measured strictly as correct refusal, the agentic system under-performs RAG here, and
the concrete remedy is a hard-abstain threshold in ranking when no candidate passes
all hard constraints. The sample is small (five queries, one run), so the result is
indicative rather than definitive.

## 5.6 Component ablation (RQ1)

The most informative experiment attributes the agentic system's advantage to a
specific component. The compliance/verification gate was switched off — replaced by
a trivial all-pass result while the rest of the pipeline was left unchanged — and the
benchmark re-run three times. Table 5.5 shows the resulting three-rung ladder.

| Rung | Overall P@5 | Simple | Medium | Hard | Δ vs previous |
|---|---|---|---|---|---|
| P2 RAG (semantic only) | 0.504 | 0.950 | 0.340 | 0.229 | — |
| P3 without compliance gate | 0.427 | 0.850 | 0.333 | 0.076 | **−0.077** |
| P3 full (gate restored) | 0.731 | 0.950 | 0.664 | 0.577 | **+0.305** |

*Table 5.5 — Component ablation: Precision@5 across the three rungs.*

![Grouped bar chart of the ablation ladder, overall and by tier: P2 RAG, P3 without the compliance gate (below RAG), and P3 full with the gate restored (highest); on hard queries the gate lifts precision from 0.076 to 0.577.](figures/figure_5_3_ablation_ladder.png)

*Figure 5.3 — Component ablation, Precision@5 overall and by difficulty tier.
Removing the compliance gate (violet) drops the agentic system below RAG; restoring
it produces the advantage, concentrated on the hardest queries. Ablation over three
runs; vector version in `figures/figure_5_3_ablation_ladder.pdf`.*

The result is decisive and somewhat unexpected. Structured discovery and ranking
*without* the verification gate are not enough — the ablated system (0.427) actually
scores below plain RAG (0.504), because casting a wide candidate net and ranking on
similarity alone does worse than RAG's tighter semantic retrieval. Restoring the gate
adds 0.305 to Precision@5, more than doubling it, and the effect is concentrated on
the hardest queries, where hard-tier precision jumps from 0.076 to 0.577. The single
component responsible for the agentic system's advantage is therefore the
compliance/quote-or-fail gate — the part that checks each candidate against each
constraint and lets ranking reward genuine constraint satisfaction rather than
surface similarity. This also explains the widening gap of Section 5.3: the gate
matters most exactly where the query is hardest. It is a more useful and more
falsifiable result than "the agent won", because it names the mechanism.

## 5.7 Diagnostic analyses

An instrumented version of the benchmark recorded, for every query, the parser's
extracted constraints, the tools it called, the number of language-model calls and
tokens, and the time spent waiting on the provider's rate limit. This section reports
what those measurements reveal about the agentic system's internal behaviour.

**Intent resolution.** The parser's extracted constraints were compared field by
field against the ground-truth constraints (Table 5.6). The parser is far more
reliable than an informal reading of the logs suggested: it extracts the structured
constraints that drive retrieval correctly 99.3% of the time.

| Constraint field | Extraction accuracy |
|---|---|
| category | 0.992 |
| country | 1.000 |
| certifications | 0.992 |
| capacity | 1.000 |
| lead time | 0.984 |
| **Overall** | **0.993** |

*Table 5.6 — Parser intent-resolution accuracy (pooled over five runs, 125
query-runs).*

**Error taxonomy.** Pooled over the 125 query-runs, the most common issue is a
"polluted product string" (16.8%), in which stray unit words enter a free-text
product field; this is cosmetic, because retrieval filters on the structured
constraints rather than that field. The genuinely harmful failures are rare: an
actual parse failure or maximum-iteration termination occurs 3.2% of the time, a
clean parse followed by zero precision 1.6%, and a missed constraint 0.8%. The
parser's real error rate is therefore low, and its most visible symptom is largely
harmless.

**Tool access.** The parser makes on average 3.1 tool calls per query, and its tool
choices track the query content: `infer_industry_context` fires on most queries,
`geocode_location` on those naming a location, `parse_quantity_unit` on those with a
capacity figure, and `canonicalize_certification` on those naming a certificate,
while the memory tool almost never fires because each benchmark query is independent.
This confirms that the tool-selection behaviour is genuine and query-appropriate
rather than decorative.

**Prompt efficiency and clean latency.** Table 5.7 reports the cost mechanism. The
agentic system makes about five language-model calls per query against RAG's one, and
uses roughly six and a half times as many tokens; this is the direct cause of its
higher dollar cost. Latency is reported net of provider pacing (Chapter 4): with the
rate-limit sleeps subtracted, the agentic system takes about 13.2 seconds of compute
per query against RAG's 2.8, roughly four and a half times slower, consistent with its
call count.

| System | LLM calls | Total tokens | Compute latency (pacing removed) | Cost / query |
|---|---|---|---|---|
| P3 | 5.3 | 7,818 | 13.2 s | $0.00140 |
| P2 | 1.0 | 1,188 | 2.8 s | $0.00030 |
| P1 | 1.0 | 352 | 3.5 s | $0.00020 |

*Table 5.7 — Prompt efficiency, clean latency, and cost per query.*

**Task success.** As a simple practical measure — whether at least one correct
supplier appears in the top five — the agentic system succeeds on 0.984 of queries,
against 0.840 for RAG and 0.000 for the single-prompt baseline.

## 5.8 Cost and operational performance (RQ3)

The gains of the agentic system come at a measured and quantified cost. Per query, it
costs about 4.7 times as much as RAG in language-model spend ($0.00140 against
$0.00030), and about 3 times as much per correct supplier returned once its higher
accuracy is taken into account. Its compute latency is several times higher, as
Table 5.7 shows. These are real trade-offs, and they define the boundary of the
recommendation: on simple queries, where the two systems are level, the additional
cost buys little, whereas on multi-constraint queries and wherever auditability is
required, it buys a substantial and significant improvement.

> **📷 Figure 5.4 — [screenshot placeholder]**
> **Attach:** the admin / metrics dashboard of the running application, showing
> per-query latency and token or cost accounting.
> **Relevance:** documents the cost and latency figures discussed in this section as
> observed in the live system.
> **Priority:** Medium.

## 5.9 Interpretation and answers to the research questions

**RQ1 — how do the paradigms compare on satisfying multi-constraint queries?** The
agentic system is significantly more precise than RAG (Precision@5 of 0.731 against
0.504; paired difference +0.227, 95% confidence interval [0.126, 0.330]), and its
advantage widens as constraints are stacked. The ablation shows this advantage is
caused by the verification gate specifically, not by retrieval or the agentic
scaffolding in general. Hypothesis H1 is therefore supported. The one qualification
is that, on a strictly like-for-like constraint-satisfaction scorer, the systems are
close; the durable win is in precision and ranking.

**RQ2 — how does auditability compare?** Auditability is structurally highest for the
agentic system (rubric score 3) and lowest for the single-prompt baseline (rubric
score 0), with RAG in between (rubric score 1), and the agentic system's recorded
judgements are 99.5% accurate against the corpus, so its evidence trail is
trustworthy. The single-prompt baseline hallucinates on every query, even when the
query is fully specified. Hypothesis H2 is supported, with the honest qualification of
Section 5.5: on impossible queries the agentic system refuses less reliably than RAG.

**RQ3 — which queries does each handle well, and where does each fail?** The
single-prompt baseline is flat at zero because it cannot use the corpus; the RAG
pipeline handles simple queries as well as the agentic system but degrades steeply on
hard ones; and the agentic system degrades most gracefully, at a real cost of roughly
five times the language-model calls and several times the latency. Hypothesis H3 is
supported.

Taken together, the results reframe supplier discovery from a naming task, at which a
plain model is already competent in the loose sense of producing plausible names,
into a trust-and-governance task, and they show empirically that it is the
verification layer — not retrieval or the agentic architecture as an undifferentiated
whole — that makes the difference. The next chapter reflects on what this means for
the gap identified at the outset, and on the strengths, weaknesses, and future
directions of the work.
