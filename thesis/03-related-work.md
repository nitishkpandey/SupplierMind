# Chapter 3: Related Work

Where the previous chapter explained the concepts this dissertation builds on,
this chapter reviews the research that has been done with them, and locates the
specific gap the dissertation fills. The review is organised by theme rather than
chronologically, because the argument is not a timeline but a map: three largely
separate bodies of work — on language agents, on retrieval-augmented generation
and its evaluation, and on the supplier-selection domain — each come close to the
problem studied here without meeting at it. Each section summarises the relevant
work, notes its limitations for this problem, and states how the present
dissertation extends or differs from it. Section 3.6 draws the threads together
and states the gap explicitly.

## 3.1 Language agents, tool use, and multi-agent systems

The idea of using a language model as the reasoning engine of a multi-step,
tool-using agent has developed rapidly, and it is the basis of the agentic
paradigm evaluated in this dissertation. The foundational contribution is the
ReAct pattern of Yao et al. (2023), which interleaves reasoning traces with tool
actions so that a model can gather information before answering; the parser in this
work uses exactly this loop. Building on the ability to act, Schick et al. (2023)
showed with Toolformer that models can learn to decide when and how to call
external tools, and Qin et al. (2024) extended tool use to thousands of real-world
APIs with ToolLLM. A complementary line of work gives agents the ability to
critique and revise their own output: Reflexion (Shinn et al., 2023) uses verbal
feedback as a form of reinforcement so that an agent improves across attempts,
which is conceptually the same mechanism as the self-checking retry step in the
system studied here. A further step is to divide a task across several specialised
agents rather than asking one model to do everything, as in MetaGPT (Hong et al.,
2024) and AutoGen (Wu et al., 2024); the five-agent design of this dissertation
follows this multi-agent principle. Wang et al. (2024) survey the broader field of
LLM-based autonomous agents and situate these mechanisms within it.

A distinction that runs through this literature, and that the present work takes a
deliberate position on, is between autonomy in an agent's *reasoning* and autonomy
in its *control flow*. Much recent work pushes towards fully autonomous
orchestration, in which the sequence of steps is itself decided by a model at run
time. That flexibility is powerful for open-ended tasks, but it comes at the cost
of predictability, and predictability is precisely what an auditable procurement
system needs: if the order of operations can change from one run to the next, the
resulting audit trail is harder to reason about and to trust. The system in this
dissertation therefore keeps its reasoning components autonomous — the parser
chooses its own tools and the evaluator decides whether to retry — while fixing the
overall order of the pipeline, a design choice discussed further in Chapter 4. The
cost of self-reflection is also relevant: mechanisms such as Reflexion (Shinn et
al., 2023) improve quality by spending additional model calls on revision, and this
dissertation measures that cost directly rather than assuming it is negligible.

This body of work establishes the *mechanisms* of agentic systems — reasoning with
tools, self-reflection, and multi-agent decomposition — and it establishes them
convincingly. Its limitation, for the purposes of this dissertation, is one of
application and of what is measured. These systems are developed and demonstrated
in general domains, and the tasks that motivate them are open-ended reasoning,
software engineering, and web interaction. None of this work applies the
mechanisms to procurement supplier discovery, and, more importantly, none of it
treats *auditability* — the traceability of each claim to evidence — as a property
to be engineered and measured. The present work differs by assembling these
mechanisms into a supplier-discovery system whose distinguishing feature is
evidence-based verification, and by measuring not only whether the system answers
well but whether its answers can be audited.

## 3.2 Retrieval-augmented generation and retrieval methods

The second body of work concerns grounding a model's output in retrieved text.
Retrieval-augmented generation was introduced by Lewis et al. (2020) as a way to
combine a parametric model with a non-parametric memory of documents, and it is the
basis of the RAG baseline in this dissertation. The retrieval component itself has
its own lineage: dense passage retrieval (Karpukhin et al., 2020) established that
learned dense embeddings can outperform traditional keyword retrieval for
question answering, and this is the family of methods the semantic side of the
hybrid retrieval used here belongs to. More recent work has made the RAG loop more
capable: Self-RAG (Asai et al., 2024) adds a self-reflective step in which the model
decides when to retrieve and critiques whether retrieved passages support its
answer, which is a close conceptual neighbour of the retrieve-then-verify design of
the agentic system studied here.

Standard RAG grounds an answer in real documents, which removes the most flagrant
form of hallucination, but it has two limitations that matter for procurement.
First, retrieval by semantic similarity has no notion of a hard numeric or
categorical constraint: it can find suppliers that are topically appropriate, but
it cannot by itself guarantee that a returned supplier's capacity exceeds a stated
minimum or that it holds a required certification. Second, the basic pattern does
not verify each individual claim against evidence, nor does it produce a record of
why a particular supplier qualifies. This dissertation differs by pairing semantic
retrieval with structured constraint filtering, so that hard constraints are
enforced exactly, and by adding a verification stage that checks each claim against
quoted evidence — the component that, as the evaluation shows, is responsible for
the agentic system's advantage.

## 3.3 Evaluation of LLM and agentic systems

Because this is a benchmarking study, the literature on *how* such systems are
evaluated is directly relevant. For retrieval, BEIR (Thakur et al., 2021)
established the value of a heterogeneous, zero-shot benchmark spanning many tasks
and domains, and it is a model for how a retrieval benchmark should be
constructed. For retrieval-augmented generation specifically, RAGAs (Es et al.,
2024) provides an automated framework for scoring properties such as faithfulness,
and the LLM-as-a-judge paradigm of Zheng et al. (2023) established both the promise
and the failure modes of using a strong language model to evaluate the outputs of
others. For agents, a set of influential benchmarks defines the current standard of
practice: SWE-bench (Jimenez et al., 2024) evaluates whether agents can resolve
real software-engineering issues, GAIA (Mialon et al., 2024) tests general
assistant abilities across difficulty levels, and AgentBench (Liu et al., 2024)
evaluates language models as agents across several environments. The idea of
organising a benchmark into difficulty tiers, which SupplierBench-25 adopts, is
visible in this work. The evaluation in this dissertation also rests on classical
information-retrieval methodology: the nDCG measure of ranked-retrieval quality
(Järvelin and Kekäläinen, 2002), the analysis of evaluation under incomplete
relevance judgements (Buckley and Voorhees, 2004), and the comparison of
significance tests that supports the use of a bootstrap test on a small benchmark
(Smucker, Allan and Carterette, 2007).

The LLM-as-a-judge paradigm deserves particular attention because it shapes a
methodological choice made here. Zheng et al. (2023) showed that a strong model can
approximate human judgement of open-ended outputs, but also that it suffers from
systematic biases — a tendency to prefer the first option presented, to reward
verbosity, and to favour outputs resembling its own. For a comparison whose whole
purpose is fairness, these biases are a liability. This dissertation therefore
avoids using a model as the arbiter of correctness and instead scores every system
against exact, pre-computed ground truth derived from the structured corpus, which
removes the judge's biases entirely; the LLM-as-a-judge literature is thus relevant
as much for the pitfall it identifies as for the technique it offers. The
faithfulness-oriented frameworks such as RAGAs (Es et al., 2024) are similarly
informative but similarly scoped to open-domain question answering rather than to
the conjunction of hard constraints that defines a procurement query.

These frameworks define how to measure retrieval quality, answer faithfulness, and
agent competence, and this dissertation adopts their tools. What they do not
provide is an evaluation targeted at multi-constraint procurement discovery. None
of the agent benchmarks concerns procurement, and none measures whether the several
constraints of a single request are satisfied together; the RAG-evaluation
frameworks measure faithfulness in open-domain question answering rather than
constraint satisfaction; and none of these treats auditability as a scored
dimension. The present work extends this literature by constructing a
domain-specific benchmark for procurement supplier discovery, and by evaluating
constraint satisfaction, verifiability, and auditability together rather than
retrieval quality alone. It also goes beyond an end-to-end score by using a
component ablation to attribute the result to a specific mechanism, which the
agent-benchmarking literature rarely does.

## 3.4 Hallucination, faithfulness, and abstention

A further strand of work concerns the reliability of what a model says. Ji et al.
(2023) provide an authoritative survey of hallucination in natural-language
generation, distinguishing its forms and reviewing mitigation strategies; this
framing underlies the way hallucination is measured in this dissertation, both as
the invention of a non-existent supplier and as the false attribution of a property
to a real one. A closely related capability is *abstention* — a system correctly
declining to answer when no correct answer exists. The methodology for testing this
originates in question answering, where Rajpurkar, Jia and Liang (2018) extended the SQuAD
reading-comprehension benchmark with deliberately unanswerable questions in order
to test whether a system knows what it does not know. The abstention set used in
this dissertation follows this methodology, presenting queries that have no
qualifying supplier and asking whether each system correctly returns nothing.

This literature supplies the vocabulary and the evaluation methodology for grounding
and abstention, and this dissertation applies both to a new setting. It differs in
domain and in framing: it measures hallucination and abstention not for
open-domain question answering but for a governed supplier-discovery task, where a
hallucinated supplier or a failure to abstain has concrete operational
consequences. It also contributes a candid finding on abstention that runs against
the expected direction, discussed in the evaluation, rather than reporting only the
favourable results.

## 3.5 Supplier selection and procurement AI

The final body of work is the application domain itself. Supplier selection has a
long and rigorous history in operations research and classical machine learning,
where it is generally framed as a multi-criteria decision problem over a fixed set
of candidate suppliers and criteria. Representative and widely cited examples
include the fuzzy VIKOR group-decision method of Sanayei, Mousavi and Yazdankhah (2010) and the
hybrid system of Kar (2015), which combines the analytic hierarchy process, fuzzy
set theory, and a neural network to rank suppliers. This literature established the
criteria and the evaluation vocabulary — price, quality, delivery, capacity,
certifications — that procurement still uses, and it solves the ranking problem
rigorously.

Its limitation, relative to this dissertation, is that it predates large language
models and frames the problem differently. It assumes that the decision arrives as
clean, structured data: the candidate set is given, the criteria are quantified,
and the task is to score and rank. It does not address the natural-language front
of the problem — parsing a sentence into machine-checkable constraints — nor the
verification of each claim against evidence, the discovery of new suppliers, or the
production of an auditable record. More recent work has begun to apply machine
learning and, very recently, large language models to supply-chain and procurement
problems, but two observations about that emerging work are relevant here. Much of
the recent machine-learning supplier-selection literature appears in
operations-research and management journals outside the scope of computer-science
indexing, and, more importantly, the work that applies *LLM-based, agentic* methods
to supplier discovery is at present almost entirely un-peer-reviewed, existing as
preprints with no established peer-reviewed benchmark or baseline. This dissertation
differs by treating supplier discovery as a natural-language, evidence-verified,
auditable task, and by providing the controlled, reproducible, peer-reviewable
comparison and benchmark that this specific setting currently lacks.

## 3.6 Synthesis: the gap and how this work addresses it

The three bodies of work reviewed above each approach the problem of this
dissertation without arriving at it. The agent literature builds the mechanisms but
applies them elsewhere and does not measure auditability. The retrieval and
RAG-evaluation literature grounds answers and measures faithfulness but does not
address multi-constraint satisfaction or auditability. The supplier-selection
literature solves a structured ranking problem but assumes the language
understanding, verification, and auditability have already been handled. The result
is that, to the best of my knowledge, no peer-reviewed study has compared the three
dominant architectural paradigms for LLM-based supplier discovery — a single-prompt
model, a retrieval-augmented pipeline, and a verification-based agentic system —
head to head on the same procurement benchmark, under an identical model, corpus,
ground truth, and scoring procedure, and measured retrieval quality, constraint
satisfaction, verifiability, and auditability together. Table 3.1 summarises this
positioning.

| Theme | Representative work | What it provides | What it does not address (the gap) |
|---|---|---|---|
| Language agents, tools, multi-agent | Yao et al. (2023); Schick et al. (2023); Qin et al. (2024); Shinn et al. (2023); Hong et al. (2024); Wu et al. (2024); Wang et al. (2024) | Mechanisms: reason–act loops, tool use, self-reflection, multi-agent decomposition | Not applied to procurement; auditability not measured |
| RAG and retrieval | Lewis et al. (2020); Karpukhin et al. (2020); Asai et al. (2024) | Grounding generation in retrieved documents; dense and self-reflective retrieval | No enforcement of hard multi-constraint satisfaction; no per-claim verification |
| Evaluation of LLM / agentic systems | Thakur et al. (2021); Es et al. (2024); Zheng et al. (2023); Jimenez et al. (2024); Mialon et al. (2024); Liu et al. (2024) | Benchmarks and metrics for retrieval, faithfulness, and agent competence | No procurement benchmark; auditability not a scored dimension; rarely component-level |
| Hallucination and abstention | Ji et al. (2023); Rajpurkar, Jia and Liang (2018) | Vocabulary for hallucination; methodology for testing abstention | Not applied to governed supplier discovery |
| IR evaluation methodology | Järvelin and Kekäläinen (2002); Buckley and Voorhees (2004); Smucker, Allan and Carterette (2007) | Ranked-retrieval metrics; sound treatment of small/incomplete-judgement benchmarks | Methodology only; not tied to this task |
| Supplier selection / procurement AI | Sanayei, Mousavi and Yazdankhah (2010); Kar (2015) | Mature multi-criteria and classical-ML supplier ranking | Predates LLMs; assumes structured input; no language parsing, verification, or auditability; LLM-agentic work is preprint-only |

*Table 3.1 — How the reviewed literature relates to this dissertation, and the gap
each theme leaves open.*

This dissertation addresses the gap in three connected ways, which motivate the
methodology of the following chapter. First, it supplies the missing controlled
comparison, holding the model and the data constant so that any measured
difference is attributable to the architecture rather than to the model or the
data. Second, it contributes a reproducible benchmark, SupplierBench-25, together
with baseline implementations of all three paradigms, to a domain that has no
established one. Third, and methodologically most distinctive, it does not stop at
an end-to-end score but uses a component ablation to attribute the agentic
system's behaviour to the specific mechanism responsible. The chapter that follows
describes how each of these was designed and built.
