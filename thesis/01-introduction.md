# Chapter 1: Introduction

## 1.1 Background and context

Sourcing is one of the oldest and most consequential tasks in any organisation
that buys goods or services. Before a contract is signed, a procurement team has
to find suppliers who can actually meet the requirement in hand, and in practice
that requirement is rarely simple. A realistic sourcing request reads something
like *"an ISO 9001 certified packaging supplier in Germany with capacity above
10,000 units per month and lead time under 30 days"*. In that single sentence
there are four separate constraints — a certification, a geography, a production
capacity, and a delivery window — and each one narrows the field of acceptable
suppliers. The analyst who receives this request typically works through a
supplier database or a search engine, filters candidates by keyword, opens each
promising result, and checks its attributes one by one against the requirement.
This is slow, and it is easy to make mistakes, but it has one property that has
historically been taken for granted: every candidate the analyst puts forward can
be pointed to, and every claim about that candidate can be checked against a
record.

The arrival of capable large language models (LLMs) has changed how this work
looks. A buyer can now paste the same sentence into a chat interface and receive
a ranked list of suppliers in seconds, and a growing number of procurement-AI
products are built on exactly this idea. Much of this recent capability comes from
two lines of research. The first is retrieval-augmented generation, introduced by
Lewis et al. (2020), in which a model's answer is grounded in documents retrieved
from a corpus rather than produced from the model's parametric memory alone; this
is now the dominant pattern in AI-assisted retrieval products. The second is the
emergence of language agents — systems in which a model reasons, calls external
tools, and acts over several steps rather than answering in a single pass. The
ReAct pattern of interleaving reasoning traces with tool use (Yao et al., 2023),
the ability of models to learn to call tools (Schick et al., 2023; Qin et al.,
2024), self-reflection and revision through verbal feedback (Shinn et al., 2023),
and the decomposition of a task across several specialised agents (Hong et al.,
2024; Wu et al., 2024) have together made it feasible to build supplier-discovery
systems that are far more sophisticated than a single prompt. Wang et al. (2024)
survey this rapidly growing field of LLM-based autonomous agents.

Convenience, however, is not the same as reliability, and this is where the
picture becomes more complicated. A language model used on its own can behave in
ways that are unacceptable for a purchasing decision. It can name suppliers that
do not exist, assert that a company holds a certification it has never been
granted, or state a production capacity that appears nowhere in any record. This
tendency of language models to produce fluent but unfounded statements is
well documented; Ji et al. (2023) provide an authoritative survey of hallucination
in natural language generation. On top of this, a plain model has no memory of a
team's earlier sourcing decisions, and its output is unstructured prose rather
than a structured, traceable record. The last point is not a matter of taste. As
automated systems are used more widely in business decisions, regulation is moving
towards requiring that those decisions be auditable. The European Union's AI Act
(Regulation (EU) 2024/1689), whose record-keeping obligations for high-risk AI
systems begin to apply from 2026, requires such systems to keep logs that make
their operation traceable over time. A supplier suggestion that cannot be traced
back to evidence is therefore not merely less useful; in a regulated workflow it
can be inadmissible.

The central tension of this dissertation follows directly from that contrast. On
the one side, an LLM makes multi-constraint supplier discovery feel effortless. On
the other, the raw output of an LLM is exactly the kind of unverifiable,
un-auditable text that a regulated procurement process cannot safely rely on. The
interesting question is therefore not whether a language model can do this task —
it plainly can, in the loose sense of producing plausible names — but what has to
be built *around* the model to make its output trustworthy, and what that extra
machinery costs.

## 1.2 Problem statement and research gap

There are three common ways to build an LLM-based supplier-discovery system today,
and they differ in how much structure and verification they place around the
language model.

The first is the **single-prompt LLM**. The query is sent straight to the model,
and the model writes the answer from its parametric knowledge. This is the
simplest possible approach and requires almost no engineering, but it produces
text that can be neither verified nor audited, and it has no access to the buyer's
actual supplier data.

The second is **retrieval-augmented generation (RAG)**. The query is embedded and
matched against a vector database of supplier descriptions, the most similar
records are retrieved, and those records are passed to the model to synthesise a
ranked answer (Lewis et al., 2020; Karpukhin et al., 2020). Because the answer is
grounded in real retrieved records, RAG is a substantial improvement over a raw
prompt, and it is the dominant pattern in current procurement-AI products.

The third is an **agentic system with verification**. Here a set of specialised
components reason about the query, retrieve candidates, verify each constraint
against quoted evidence, and produce a structured, ranked, and logged result. This
is considerably more complex to build, but it is designed from the outset to be
auditable. This third paradigm is realised in this dissertation as **SupplierMind**;
Figure 1.1 shows what it does at a glance, and the full design is developed in
Chapter 4.

![SupplierMind at a glance: a multi-constraint procurement query passes through four stages — understand, retrieve, verify, rank — to produce an auditable shortlist, underpinned by three properties: grounded in governed data, evidence-verified, and fully auditable.](figures/figure_1_1_at_a_glance.png)

*Figure 1.1 — SupplierMind at a glance. A procurement query with stacked constraints
is parsed into machine-checkable fields, matched against the buyer's governed data,
verified constraint-by-constraint against quoted evidence, and ranked
deterministically into an auditable shortlist. The lower panel summarises the three
properties — grounded, verified, auditable — that turn a list of names into a
defensible procurement decision.*

The gap this dissertation addresses is that, to the best of my knowledge, no
published study has compared all three of these architectures head to head on the
same procurement benchmark. RAG is widely adopted because it is the simplest step
beyond a raw prompt, and the more elaborate agentic design is often assumed to be
better because it does more. But whether that additional complexity actually pays
off — in terms of how many constraints are satisfied correctly, how verifiable and
auditable the output is, and at what cost in latency and computation — has not
been measured in a controlled way for this task. This gap is not accidental. The
literature on language agents and the standard agent benchmarks that evaluate them,
such as SWE-bench (Jimenez et al., 2024), GAIA (Mialon et al., 2024), and
AgentBench (Liu et al., 2024), target software engineering, general web
assistance, and API manipulation, and none of them measures auditability. The
retrieval literature and its evaluation frameworks, such as BEIR (Thakur et al.,
2021) and RAGAs (Es et al., 2024), measure retrieval quality and answer
faithfulness in open-domain question answering, but not the simultaneous
satisfaction of several hard, structured constraints that defines a procurement
query. And the mature literature on supplier selection in operations research and
classical machine learning (Sanayei, Mousavi and Yazdankhah, 2010; Kar, 2015) predates large
language models and treats the problem as ranking over a clean, structured table
rather than as a natural-language discovery task with evidence-based verification.
The three bodies of work that bear on this problem, in other words, do not meet at
the point this dissertation studies. Chapter 3 (Related Work) develops this
argument in full.

## 1.3 Research aim, questions, and objectives

The aim of this dissertation is to determine, through a controlled benchmarking
study, how the single-prompt, RAG, and agentic paradigms compare for
multi-constraint procurement supplier discovery, and to identify which parts of
the more complex agentic design, if any, are responsible for its behaviour. Three
research questions structure the investigation.

**RQ1 — How do single-prompt LLM, RAG, and agentic architectures compare on
satisfying multi-constraint procurement queries?** The associated hypothesis (H1)
is that the agentic architecture, because it verifies each constraint against
evidence, will satisfy more constraints correctly than the other two paradigms,
and that the gap will widen as the number of stacked constraints in a query
increases.

**RQ2 — How does auditability, defined as the ability to link supplier claims back
to specific evidence, compare across the three architectures?** The hypothesis
(H2) is that auditability will be structurally highest in the agentic
architecture, because every claim it produces is tied to a quoted piece of
evidence, lowest in the single-prompt approach, which produces unstructured prose,
and intermediate for RAG.

**RQ3 — Which kinds of queries does each architecture handle well, and where does
each one fail?** The hypothesis (H3) is that single-prompt models will perform
reasonably on simple queries but degrade sharply on hard, multi-constraint ones;
that RAG will handle clear queries well but struggle with ambiguity; and that the
agentic architecture will degrade most gracefully, but pay a real cost in latency.

From these questions, the concrete objectives of the work are: to implement the
three paradigms so that they can be evaluated under identical conditions; to
construct a reproducible benchmark of multi-constraint procurement queries with
verifiable ground truth; to evaluate all three paradigms across retrieval quality,
constraint satisfaction, verifiability, and auditability with appropriate
statistical treatment; and to go beyond an end-to-end comparison by using an
ablation to attribute the agentic system's behaviour to specific components.

## 1.4 Significance and relevance

The significance of this work is both practical and academic. It was carried out in
collaboration with Mercanis (Cdc3 GmbH), a procurement-technology startup based in
Berlin, Germany, whose practical framing of the multi-constraint sourcing problem
motivated the study and grounded it in the realities of how procurement teams
actually work; to preserve confidentiality, no proprietary or customer data was
used, and the evaluation relies entirely on a synthetic corpus (Section 4.4).

For practice, procurement is a high-stakes domain in which a wrong or
unverifiable answer has real consequences. Onboarding a supplier who turns out not
to hold a claimed certification, or who is in fact subject to sanctions, is not a
minor inconvenience but a legal and financial exposure. As organisations adopt
LLM-based tools for sourcing, and as regulation such as the EU AI Act begins to
require that automated decisions be logged and traceable, buyers need evidence
about *when* the added cost of an agentic, verification-based system is worth
paying and when a simpler pipeline is sufficient. This dissertation provides that
evidence, and in doing so it reframes the question that procurement teams should
be asking. The right question is not whether an LLM can name a supplier — a
general-purpose chatbot with web access can already do that — but whether the
system can produce a supplier decision that is grounded in the organisation's own
data, verified against evidence, and defensible to an auditor. Discovery in
procurement, on this view, is not a naming problem but a trust-and-governance
problem, and the results reported here show empirically which architectural
choices actually address it.

For research, the work offers a template and a resource that the surrounding
literature currently lacks. It is, to the best of my knowledge, the first
controlled comparison of these three paradigms for procurement supplier discovery,
holding the model and the data constant so that differences are attributable to
the architecture. It contributes a reproducible benchmark to a domain that has no
established one. And, methodologically, it demonstrates the value of moving beyond
a single end-to-end score: by ablating a component, the study attributes the
agentic advantage to a specific mechanism rather than to the architecture as an
undifferentiated whole, which is a more useful and more falsifiable form of
result than "the agent won". The evaluation follows established
information-retrieval practice for small, curated benchmarks (Järvelin and
Kekäläinen, 2002; Buckley and Voorhees, 2004; Smucker, Allan and Carterette, 2007), which makes
the comparison defensible rather than anecdotal.

## 1.5 Scope and key challenges

Several genuine challenges had to be addressed for the comparison to be
meaningful. The first is understanding the query. A procurement request is a
compact natural-language sentence in which several constraints are entangled, and
turning it reliably into machine-checkable fields — a category, a certification, a
capacity value with its unit, a lead-time ceiling, a location with a radius — is
non-trivial; the agentic system uses a ReAct reasoning loop (Yao et al., 2023) and
a small set of domain tools to do this. The second is verification: rather than
letting the model assert that a supplier meets a constraint, the system must check
each claim against stored evidence, which requires a discipline that a fluent
model does not naturally follow. The third is evaluation design. A fair comparison
of three architectures demands identical conditions, an objective and
reproducible notion of ground truth, and statistical treatment appropriate to a
small benchmark, so that a reported difference reflects the architecture and not
chance or an artefact of the setup. A fourth, more practical challenge was running
a reproducible benchmark under the rate limits of free-tier providers without
compromising the results.

The scope of the study is deliberately bounded, and the boundaries are stated
honestly so that the claims are not overread. The benchmark consists of
twenty-five carefully curated queries and a five-query abstention set, which is a
seed benchmark rather than a large-scale one; twenty-five is what a single
annotator can curate carefully and consistently while still covering three
difficulty tiers. The supplier corpus is ten thousand synthetic records generated
procedurally with documented parameters and a fixed seed, which yields exact,
uncontestable ground truth but does not capture the messiness of real company
data. The queries are in English, and the domain is procurement supplier
discovery specifically. The primary language model is a single pinned model
(OpenAI's gpt-4o-mini), chosen so that results are reproducible. On the technical
side, the study uses pretrained deep-learning models — transformer-based language and
embedding models — as components; it does not train or design neural networks, and
image-oriented architectures such as convolutional neural networks are out of scope,
since the task is text-based rather than visual. These limits mean the work is best
understood as a rigorous, reproducible case study rather than a universal claim about
agents, and Chapter 6 returns to them in detail.

## 1.6 Contributions

The specific contributions of this dissertation are the following.

1. **A controlled three-paradigm comparison.** A single-prompt LLM, a RAG
   pipeline, and a verification-based agentic system are evaluated on the same
   queries, corpus, ground truth, and scoring code, across four metric families
   (constraint satisfaction, verifiability, auditability, and operational
   performance). This is, to the best of my knowledge, the first head-to-head
   comparison of these paradigms for multi-constraint procurement supplier
   discovery. The headline finding, reported in full in Chapter 5, is that the
   agentic system is significantly more precise than RAG, and that its advantage
   widens as more constraints are stacked in a query.

2. **SupplierBench-25, a reproducible benchmark.** A public benchmark of
   twenty-five multi-constraint procurement queries across three difficulty tiers,
   together with a five-query abstention set of intentionally unsatisfiable
   requests, over a ten-thousand-supplier synthetic corpus with hand-verified
   ground truth. Baseline implementations of all three paradigms are released with
   it so that the comparison can be repeated and extended.

3. **A component ablation that attributes the advantage.** Rather than stopping at
   an end-to-end score, the study switches off the agentic system's per-constraint
   verification gate and re-runs the benchmark. The result is decisive and
   somewhat unexpected: without the gate the agentic pipeline scores *below* plain
   RAG, and restoring it produces a large gain that is concentrated on the hardest
   queries (the exact figures are given in Chapter 5). The advantage of the
   agentic design is therefore shown to come from verification specifically, not
   from the retrieval or the agentic scaffolding in general.

4. **A documented architectural pattern.** The dissertation documents a
   supplier-discovery architecture that combines ReAct-style query parsing (Yao et
   al., 2023), hybrid retrieval that fuses semantic vector search with structured
   constraint filtering, a quote-or-fail rule that verifies each claim against
   quoted evidence, deterministic and explainable ranking, and a unified audit
   log.

5. **An honest and extended evaluation.** The metric suite is extended beyond the
   original proposal to include rank-aware measures such as nDCG (Järvelin and
   Kekäläinen, 2002) and mean average precision, a harmonised constraint-
   satisfaction score that removes self-scoring bias, hallucination and abstention
   measures, parser intent-resolution accuracy, and clean latency and prompt-
   efficiency measurements, all reported with bootstrap confidence intervals and a
   paired significance test (Smucker, Allan and Carterette, 2007). The study also reports a
   genuine negative result: on impossible queries the agentic system abstains less
   reliably than RAG, which is discussed openly rather than omitted.

The complete implementation, the benchmark and its baselines, and the scripts that
reproduce every reported number are available in the project's public GitHub
repository at <https://github.com/nitishkpandey/SupplierMind>, which also supports
the technical-contribution requirement of the programme.

## 1.7 Structure of the dissertation

The remainder of the dissertation is organised as follows.

**Chapter 2 (Foundations)** introduces the concepts a reader needs in order to
follow the rest of the work, both from the procurement business domain and from
the technical side — language models and their limitations, embeddings and vector
search, retrieval-augmented generation, the agent and tool-use paradigm, and the
information-retrieval metrics used later. It is deliberately foundational and does
not survey the research literature.

**Chapter 3 (Related Work)** reviews the existing research relevant to the study,
organised by theme — language agents and tool use, retrieval-augmented generation,
the evaluation of LLM and agentic systems, hallucination and abstention, and the
supplier-selection domain — and identifies the specific gap that this dissertation
fills, extending the argument sketched in Section 1.2.

**Chapter 4 (Approach)** describes the research approach and the technical design
in detail: the three paradigms, the five-agent architecture of the agentic system
and the role of each agent, the hybrid retrieval and quote-or-fail verification
mechanisms, the ranking model, the construction of the benchmark and its ground
truth, and the reproducibility details including the tools, frameworks, data, and
environment used.

**Chapter 5 (Evaluation and Results)** presents the experimental setup, the
baselines, and the metrics, and reports the results systematically: the headline
comparison across the three paradigms, the breakdown by difficulty tier, the
component ablation, the auditability and hallucination findings, the abstention
result, and the cost analysis, together with their statistical treatment and their
implications for the three research questions.

**Chapter 6 (Conclusion)** reflects on how the findings address the gap identified
here, discusses the strengths and weaknesses of the approach, summarises the
contributions and key results, and sets out concrete directions for future work.

The dissertation closes with the **References** and, where useful, **Appendices**
containing supporting material that is valuable but not essential to the main
argument.
