# Chapter 6: Conclusion

This final chapter draws the dissertation together. It restates what was done and
what was found, revisits the research questions and objectives to show how each was
met, reflects on the strengths and weaknesses of the approach, and sets out concrete
directions for future work that build on the limitations and open questions
identified along the way.

## 6.1 Summary of the work

The dissertation set out to answer a question that current practice largely assumes
rather than tests. Language models make multi-constraint supplier discovery feel
effortless, and retrieval-augmented pipelines are already the dominant pattern in
procurement-AI products, yet the raw output of a language model is exactly the kind
of unverifiable, un-auditable text that a regulated procurement process cannot
safely rely on. The interesting question was therefore not whether a model can do
the task, but what architecture around it makes the output trustworthy, and what
that additional complexity costs.

To answer this, three architectural paradigms — a single-prompt language model, a
retrieval-augmented generation pipeline, and a verification-based agentic system —
were compared head to head under identical conditions on the same benchmark. The
comparison was built on SupplierBench-25, a reproducible benchmark of twenty-five
multi-constraint procurement queries across three difficulty tiers over a
ten-thousand-supplier synthetic corpus, together with a five-query abstention set of
deliberately unsatisfiable requests. The agentic system, SupplierMind, was built as
a five-agent pipeline that parses a query with a ReAct reasoning loop, retrieves
candidates by combining semantic and structured search, verifies each constraint
against quoted evidence, ranks deterministically, and records an audit trail. All
three paradigms were measured across retrieval quality, constraint satisfaction,
verifiability, and auditability, with bootstrap confidence intervals and a paired
significance test, and — most distinctively — a component ablation was used to
attribute the result to a specific mechanism rather than to the architecture as a
whole.

## 6.2 How the research questions and objectives were met

The three research questions were each answered by the evaluation. On **RQ1**, the
agentic system was found to be significantly more precise than the retrieval
baseline (a Precision@5 of 0.731 against 0.504, a paired difference of +0.227 with a
95% confidence interval of [0.126, 0.330]), and its advantage widened as more
constraints were stacked in a query, which is what hypothesis H1 predicted. On
**RQ2**, auditability was structurally highest for the agentic system and lowest for
the single-prompt baseline, with the agentic system's recorded per-constraint
judgements shown to be accurate 99.5% of the time against the corpus, supporting
hypothesis H2. On **RQ3**, the single-prompt baseline was flat at zero because it
cannot use the corpus, the retrieval pipeline degraded steeply on hard queries, and
the agentic system degraded most gracefully, at a real and quantified cost in
language-model calls and latency, supporting hypothesis H3.

The concrete objectives set out in the introduction were correspondingly met. The
three paradigms were implemented so that they could be evaluated under identical
conditions; a reproducible benchmark with verifiable ground truth was constructed;
all three were evaluated across the four metric families with appropriate
statistical treatment; and the study went beyond an end-to-end comparison to
attribute the agentic system's behaviour to specific components through the
ablation. The research problem — determining whether the additional complexity of an
agentic design pays off for multi-constraint procurement discovery, and where it
does not — was thereby addressed directly and with evidence.

## 6.3 How the findings address the identified gap

The introduction and related-work chapters located the gap at the meeting point of
three literatures that do not otherwise meet: the language-agent literature, which
builds the mechanisms but applies them to other domains and does not measure
auditability; the retrieval and RAG-evaluation literature, which grounds answers and
measures faithfulness but not multi-constraint satisfaction or auditability; and the
supplier-selection literature, which solves a structured ranking problem but assumes
the language understanding, verification, and auditability have already been handled.
The dissertation closes this gap in three connected ways. It supplies the missing
controlled comparison, holding the model and the data constant so that differences
are attributable to the architecture. It contributes a reproducible benchmark, with
baseline implementations of all three paradigms, to a domain that had no established
one. And it moves beyond an end-to-end score to attribute the agentic advantage to a
specific mechanism — the per-constraint verification gate — which is a more useful
and more falsifiable result than a claim that "the agent won".

The most consequential finding is precisely this attribution. The ablation showed
that structured discovery and ranking *without* the verification gate score below
plain retrieval, and that restoring the gate more than doubles precision on the
hardest queries. In other words, the value of the agentic design lies not in the
retrieval machinery, nor in the agentic scaffolding in general, but specifically in
the discipline of checking each claim against evidence. This reframes supplier
discovery from a naming task, at which a plain model is already competent in the
loose sense of producing plausible names, into a trust-and-governance task, and it
identifies which architectural choice actually addresses it.

## 6.4 Strengths of the approach

The principal strength of the approach is its internal validity. By holding the
model, the corpus, the ground truth, and the scoring code constant across all three
paradigms, the study can attribute differences to the architecture rather than to
confounds, and by using a synthetic corpus it obtains exact, uncontestable ground
truth that makes scoring objective and fully reproducible. A second strength is
methodological honesty: the results are reported with confidence intervals and a
significance test appropriate to a small benchmark, the comparison of
constraint-satisfaction scores is harmonised to remove self-scoring bias, and a
genuine negative result is reported rather than omitted. A third strength is the
component ablation, which turns a comparison into an explanation. Finally, the whole
study is reproducible: the corpus is generated from a fixed seed, the model is
pinned, and every reported number is produced by a committed script in a public
repository.

## 6.5 Weaknesses and limitations

The weaknesses of the approach are stated plainly, because doing so is part of what
makes the work defensible. The benchmark is small — twenty-five scored queries and a
five-query abstention set, curated by a single annotator — so it is best understood
as a seed benchmark and a rigorous case study rather than a definitive, large-scale
evaluation. The supplier corpus is synthetic, which secures exact ground truth at
the cost of the messiness of real company data. The study uses a single, pinned
language model, so a difference that is architectural in this setting has not been
confirmed to hold across models. The agentic system's most distinctive capability,
discovery of new suppliers from the web, is implemented and integrated but is not
exercised by the benchmark, which runs against the fixed corpus; its advantages are
therefore argued architecturally rather than measured. Recall is weak on this
benchmark by construction, because simple queries have many correct answers, so
precision rather than recall is the measure to trust. And, as reported openly, the
agentic system abstains less reliably than the retrieval baseline on impossible
queries, returning auditable near-misses instead of an empty result.

## 6.6 Future work

Several directions follow naturally from these limitations, in rough order of value.
The first is a **cross-model check**: re-running at least one difficulty tier on a
second, independent language model would establish whether the architectural finding
holds beyond the model used here, and is the single most valuable next experiment.
The second is a **purpose-built web-discovery experiment**: the system's ability to
find, validate, and screen new suppliers from the web is its most distinctive
capability and the one the current benchmark does not measure, and an evaluation that
scores web-discovered suppliers on verifiability — a real source, a validated
address, a sanctions clearance — would turn an architectural argument into measured
evidence. The third is to **scale the benchmark**: a larger, multi-annotator query
set with inter-annotator agreement, and ideally a real rather than synthetic corpus,
would raise the external validity of the findings. The fourth is a concrete
engineering fix suggested directly by the abstention result: a **hard-abstain
threshold** in the ranking layer, so that when no candidate passes all hard
constraints the system returns nothing rather than near-misses. A fifth is
**cost-aware routing**, sending simple queries — where the agentic system and the
retrieval baseline are level — to the cheaper pipeline, and reserving the agentic
path for the hard, multi-constraint, audit-sensitive queries where it is worth its
cost.

## 6.7 Concluding remarks

The contribution of this dissertation is, at heart, to replace an assumption with
evidence. The assumption, widespread in practice, is that a more elaborate agentic
system is better because it does more; the evidence shows that this is true for
multi-constraint procurement discovery, but for a specific reason — the verification
of each claim against evidence — and at a specific, quantified cost. Along the way,
the work delivers a reproducible benchmark and baseline implementations that a
domain lacking them can build on, and it treats auditability not as a marketing
claim but as a property to be measured. In a setting where automated decisions are
increasingly expected to be traceable and defensible, the central lesson is a simple
one: for supplier discovery, the value of the agentic approach is not that it can
name a supplier, but that it can produce a supplier decision that can be verified,
audited, and defended — and it is the verification layer, above all, that makes the
difference.
