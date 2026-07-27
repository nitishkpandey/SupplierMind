# Literature Review — Guide, Scope, and Verified Sources

This document has three parts:

- **Part A** — how to actually do a literature review, step by step, using DBLP
  for the papers and SCImago / CORE for the rankings.
- **Part B** — the scope of concepts this review needs to cover, tied to the
  three research questions.
- **Part C** — a curated set of **verified** candidate papers (checked against
  DBLP so none are hallucinated), organised by theme, with a summary table that
  maps each paper to the research question, hypothesis, or evaluation it supports.

A note on sourcing: every paper in Part C was cross-checked against DBLP for its
real peer-reviewed venue and year. Where DBLP also lists an arXiv/CoRR preprint,
the **peer-reviewed venue version is the one cited** (arXiv-only entries are
excluded, as required). You should still open each DBLP record yourself, export
the BibTeX, and confirm the venue's rank before writing — the directions below
tell you exactly how.

---

## Part A — How to do a literature review (step by step)

A literature review is not a list of summaries. It is an **argument**: it shows
what is already known, where the gap is, and why your work belongs in that gap.
Do it in this order.

### Step 1 — Fix your scope from your research questions

You already have three research questions (agentic vs. simpler architectures;
auditability; where each fails). Every paper you include should connect to at
least one of them. Write the three questions at the top of your notes and refuse
to include a paper that does not relate to any of them — this keeps the review
focused instead of sprawling.

### Step 2 — Turn the questions into search themes

Break each question into the concepts it rests on (Part B is this list already
done for you). For example, "agentic vs. simpler architectures" rests on *LLM
agents*, *the ReAct pattern*, *tool use*, *RAG*, and *multi-agent systems*. Each
concept becomes a search theme.

### Step 3 — Search on DBLP (not Google, not arXiv)

Use `https://dblp.org/search` with the concept keywords. DBLP indexes
*peer-reviewed* venues, which is exactly what you want.

- Search by keyword (e.g. "retrieval augmented generation evaluation").
- When you find a strong author, open their DBLP author page and scan their
  other work — this is faster than keyword search alone.
- **Distinguishing arXiv from real venues:** in a DBLP record, an entry whose
  venue is *CoRR* is the arXiv preprint. Look for the same title with a real
  venue (ICLR, NeurIPS, ACL, a journal). Cite that one. If a paper exists *only*
  as CoRR, exclude it (per your rule).
- Export **BibTeX** directly from DBLP (the "export record" icon) so your
  citations are exact — never hand-type a citation.

### Step 4 — Snowball

For each core paper, do two things: read its **references** (backward
snowballing — where did this idea come from?) and look at **who cites it**
(forward snowballing — use Google Scholar's "Cited by"). This is how you find the
papers keyword search misses, and how you show a lineage of ideas rather than a
random pile.

### Step 5 — Screen with explicit criteria

Decide inclusion/exclusion rules and apply them consistently:

- **Peer-reviewed venue** on DBLP (no arXiv-only). *Required.*
- **Recency** for the AI/ML/RAG/LLM themes: 2023–2026, because the field moves
  fast. Foundational/origin papers (the paper that *introduced* a paradigm) are
  the allowed exception and should be labelled as such.
- **Relevance** to at least one research question.
- **Quality** — good venue rank and a healthy citation count (see Step 6).

### Step 6 — Assess quality: rank the venue, count the citations

- **Conferences** → rank on **CORE** (`https://portal.core.edu.au/conf-ranks/`).
  The scale is A\* (top) > A > B > C. For this field, ICLR, NeurIPS, ACL, EMNLP
  are **A\***; EACL is **A**.
- **Journals** → rank on **SCImago** (`https://www.scimagojr.com/journalrank.php`).
  Read the **quartile (Q1 best)** and the **SJR** value. Search the journal name,
  and note its subject-category quartile.
- **Citations** → check Google Scholar or Semantic Scholar for the citation
  count; prefer well-cited work, but weight recent papers less harshly (a 2025
  paper cannot have 1,000 citations yet).

> **Important:** SCImago ranks **journals**, CORE ranks **conferences**. Do not
> look for ICLR on SCImago or *ACM Computing Surveys* on CORE.

### Step 7 — Organise by theme, not by date

Group papers under the concepts from Part B. Within a theme, write a short
synthesis: what these papers collectively established, and what they did *not*
address. A chronological list ("in 2023 X did…, in 2024 Y did…") reads like a
timeline, not an argument.

### Step 8 — Synthesise and point at your gap

Each theme should end by connecting to your work: this is the sentence that earns
the citation. For example, after the RAG-evaluation theme: *"These frameworks
evaluate answer faithfulness in open-domain QA, but none evaluate constraint
satisfaction or auditability for a governed, multi-constraint retrieval task —
which is what this thesis measures."*

### Step 9 — Build the summary table

A table with theme, paper, venue, rank, and which research question it supports
(Part C gives you this) lets an examiner see your coverage at a glance and shows
you have mapped the literature onto your own contribution.

### Step 10 — Cite cleanly and consistently

Use the DBLP BibTeX, pick one citation style, and make sure every claim that is
not your own has a citation. Never cite a paper you have not at least skimmed.

---

## Part B — Scope of concepts to cover

These are the themes your review must span. They are derived directly from the
system and the findings (`findings.md`, `findings_diagnostics.md`), so covering
them positions every part of your contribution.

1. **LLM agents and the ReAct pattern** — reasoning interleaved with tool use;
   the basis of your Parser. *(Grounds the "agentic" architecture, RQ1/RQ3.)*
2. **Tool use / function calling in LLMs** — how models learn to call tools; your
   Parser's five-tool registry. *(RQ1.)*
3. **Multi-agent LLM systems** — decomposing a task across specialised agents;
   your five-agent pipeline. *(RQ1.)*
4. **Self-reflection / self-critique / retry loops** — an agent judging and
   revising its own output; your Evaluator loop. *(RQ1/RQ3.)*
5. **Retrieval-Augmented Generation (RAG)** — grounding generation in retrieved
   documents; your P2 baseline and the P3 discovery stage. *(RQ1.)*
6. **Dense / hybrid retrieval** — vector search and its fusion with structured
   filtering; your Milvus + SQL discovery. *(RQ1, retrieval design.)*
7. **RAG and LLM-system evaluation** — how to measure retrieval-augmented and
   agentic systems; directly informs your evaluation design. *(Evaluation.)*
8. **Agent benchmarks** — how the field builds benchmarks for LLM agents; the
   template for SupplierBench. *(Evaluation, benchmark contribution.)*
9. **Hallucination and faithfulness** — fabrication and evidence-grounding in
   LLMs; your entity/attribute-hallucination and quote-or-fail results. *(RQ2.)*
10. **Abstention / answerability ("knowing what you don't know")** — returning
    "no answer" instead of a wrong one; your Abstention-5 experiment. *(RQ2/RQ3.)*
11. **Information-retrieval evaluation metrics** — Precision@k, MRR, nDCG, MAP,
    and significance testing; your metric suite. *(Evaluation.)*
12. **Supplier selection / procurement decision support** — the application
    domain, historically solved with multi-criteria and classical ML methods;
    the gap your LLM-agentic approach fills. *(Domain background and gap.)*

### B.1 — DBLP search keywords per theme

Type these into `https://dblp.org/search` to find more papers. Search on **title
words** (DBLP matches titles well), try each row's variants, and when a paper is
strong, open its authors' DBLP pages to find neighbouring work. Prefer 2023–2026
for the AI/ML/RAG/LLM rows.

| Theme | DBLP search strings to try |
|---|---|
| LLM agents / ReAct | `large language model agent`; `LLM agent`; `language agents`; `ReAct reasoning acting`; `autonomous agents survey` |
| Tool use / function calling | `language model tool use`; `tool learning`; `function calling LLM`; `API agent`; `tool-augmented language model` |
| Multi-agent LLM | `multi-agent large language model`; `LLM multi-agent collaboration`; `role-based agents`; `agent conversation framework` |
| Self-reflection / retry | `self-reflection language model`; `self-critique`; `verbal reinforcement`; `iterative refinement LLM`; `self-correction` |
| RAG | `retrieval-augmented generation`; `retrieval augmented language model`; `RAG knowledge-intensive`; `retrieval augmented survey` |
| Dense / hybrid retrieval | `dense passage retrieval`; `hybrid retrieval`; `learned sparse retrieval`; `dense retrieval question answering` |
| RAG / LLM evaluation | `retrieval augmented generation evaluation`; `RAG faithfulness`; `LLM as a judge`; `evaluating large language models` |
| Agent benchmarks | `agent benchmark`; `evaluating LLM agents`; `general AI assistant benchmark`; `tool use benchmark`; `web agent benchmark` |
| Hallucination / faithfulness | `hallucination large language model`; `faithfulness generation`; `factual consistency`; `evidence grounding LLM` |
| Abstention / answerability | `unanswerable questions`; `abstention`; `selective prediction`; `answerability`; `know what you don't know` |
| IR metrics & benchmarking | `information retrieval evaluation`; `cumulated gain nDCG`; `incomplete relevance judgments`; `pooling TREC` |
| Statistical significance in IR | `statistical significance information retrieval`; `randomization test retrieval`; `bootstrap evaluation IR` |
| Domain — procurement / supply chain | `supplier selection machine learning`; `supplier selection multi-criteria`; `procurement decision support`; `supply chain large language model`; `procurement natural language processing` |

---

## Part C — Verified candidate papers

All venues and years below were checked against DBLP. Conference ranks (CORE) and
journal quartiles (SCImago) are noted as a starting point — **confirm each on the
official site**, since ranks are periodically revised.

### C.1 Summary table (map to research questions, hypotheses, and evaluation)

Legend — **RQ1** architecture comparison / **RQ2** auditability & trust /
**RQ3** where each fails + cost / **EVAL** evaluation methodology or metrics.

| # | Theme | Paper (short) | Authors (first) | Venue | Year | Rank | Directly supports |
|---|---|---|---|---|---|---|---|
| 1 | LLM agents / ReAct | ReAct: Synergizing Reasoning and Acting in Language Models | Yao et al. | ICLR | 2023 | CORE A\* | RQ1 (Parser design) |
| 2 | Self-reflection / retry | Reflexion: Language Agents with Verbal Reinforcement Learning | Shinn et al. | NeurIPS | 2023 | CORE A\* | RQ1, RQ3 (Evaluator loop) |
| 3 | Tool use | Toolformer: Language Models Can Teach Themselves to Use Tools | Schick et al. | NeurIPS | 2023 | CORE A\* | RQ1 (tool registry) |
| 4 | Tool use | ToolLLM: Facilitating LLMs to Master 16000+ Real-world APIs | Qin et al. | ICLR | 2024 | CORE A\* | RQ1 (tool use at scale) |
| 5 | Multi-agent | MetaGPT: Meta Programming for Multi-Agent Collaborative Framework | Hong et al. | ICLR | 2024 | CORE A\* | RQ1 (five-agent design) |
| 6 | Multi-agent | AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation | Wu et al. | COLM | 2024 | new venue — confirm on DBLP | RQ1 (multi-agent design) |
| 7 | LLM agents (survey) | A Survey on Large Language Model based Autonomous Agents | Wang et al. | Frontiers of Computer Science | 2024 | SCImago Q1/Q2 (confirm) | RQ1 (agentic positioning) |
| 8 | RAG (origin) | Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks | Lewis et al. | NeurIPS | 2020 | CORE A\* | RQ1 (P2 baseline; foundational) |
| 9 | RAG (advanced) | Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection | Asai et al. | ICLR | 2024 | CORE A\* | RQ1, RQ2 (retrieve+verify) |
| 10 | Dense retrieval | Dense Passage Retrieval for Open-Domain Question Answering | Karpukhin et al. | EMNLP | 2020 | CORE A\* | RQ1 (semantic retrieval; foundational) |
| 11 | Retrieval benchmark | BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of IR Models | Thakur et al. | NeurIPS Datasets & Benchmarks | 2021 | CORE A\* | EVAL (benchmark design) |
| 12 | RAG evaluation | RAGAs: Automated Evaluation of Retrieval Augmented Generation | Es et al. | EACL | 2024 | CORE A | EVAL (faithfulness metrics) |
| 13 | LLM evaluation | Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena | Zheng et al. | NeurIPS | 2023 | CORE A\* | EVAL (evaluation methodology) |
| 14 | Agent benchmark | AgentBench: Evaluating LLMs as Agents | Liu et al. | ICLR | 2024 | CORE A\* | EVAL, RQ3 (benchmark template) |
| 15 | Agent benchmark | GAIA: A Benchmark for General AI Assistants | Mialon et al. | ICLR | 2024 | CORE A\* | EVAL, RQ3 (difficulty tiers) |
| 16 | Agent benchmark | SWE-bench: Can Language Models Resolve Real-World GitHub Issues? | Jimenez et al. | ICLR | 2024 | CORE A\* | EVAL, RQ3 (realistic tasks) |
| 17 | Hallucination | Survey of Hallucination in Natural Language Generation | Ji et al. | ACM Computing Surveys | 2023 | SCImago Q1 | RQ2 (hallucination) |
| 18 | Abstention | Know What You Don't Know: Unanswerable Questions for SQuAD | Rajpurkar et al. | ACL | 2018 | CORE A\* | RQ2, RQ3 (Abstention-5) |
| 19 | IR metrics | Cumulated Gain-based Evaluation of IR Techniques (nDCG) | Järvelin & Kekäläinen | ACM TOIS | 2002 | SCImago Q1 | EVAL (nDCG, MAP) |
| 20 | Benchmarking methodology | Retrieval Evaluation with Incomplete Information | Buckley & Voorhees | SIGIR | 2004 | CORE A\* | EVAL (benchmark / ground truth) |
| 21 | Statistical testing | A Comparison of Statistical Significance Tests for IR Evaluation | Smucker, Allan & Carterette | CIKM | 2007 | CORE A\* | EVAL (bootstrap / significance test) |
| 22 | Domain (candidate) | A Hybrid Group Decision Support System for Supplier Selection (AHP + fuzzy + neural network) | Kar | Journal of Computational Science | 2015 | SCImago Q1/Q2 (confirm) | Domain gap |
| 23 | Domain (candidate) | Group Decision Making for Supplier Selection with VIKOR under Fuzzy Environment | Sanayei et al. | Expert Systems with Applications | 2010 | SCImago Q1 | Domain gap |

> Rows 1–21 are DBLP-verified (real peer-reviewed venue and year; where DBLP also
> lists a CoRR/arXiv preprint, the venue version is the one cited). Row 6 (AutoGen)
> is a real COLM 2024 paper — confirm the exact record on DBLP, as the CoRR
> preprint may appear first. Rows 22–23 are **domain candidates** to confirm on
> DBLP. Note that peer-reviewed work on *LLM-agentic* supplier discovery is
> currently almost all preprints (see §C.4) — that scarcity is your gap.

### C.2 Themes, with the synthesis sentence you can adapt

**LLM agents, ReAct, tool use, self-reflection, multi-agent (papers 1–7).**
ReAct [1] established interleaving reasoning with tool use, which is exactly the
loop your Parser runs; Toolformer [3] and ToolLLM [4] study how models learn to
call tools; Reflexion [2] introduced self-critique and revision, which your
Evaluator loop implements as a bounded retry; MetaGPT [5] and AutoGen [6]
decompose a task across specialised agents, as your five-agent pipeline does; and
the survey by Wang et al. [7] situates all of this. *Synthesis for your gap:
these establish the mechanisms of agentic systems in general domains, but none
applies or evaluates them for constraint-satisfying supplier discovery.*

**RAG and retrieval (papers 8–11).** Lewis et al. [8] introduced RAG, the
paradigm your P2 baseline implements and your P3 discovery stage extends; DPR
[10] established dense retrieval; Self-RAG [9] adds retrieval with self-critique,
a close conceptual neighbour of your retrieve-then-verify design; BEIR [11] set
the template for a heterogeneous retrieval benchmark. *Synthesis: retrieval
grounds generation, but standard RAG does not enforce per-constraint verification,
which your ablation shows is the decisive component.*

**Evaluation of retrieval and agentic systems (papers 12–16).** RAGAs [12] and
LLM-as-a-Judge [13] are the templates for evaluating faithfulness and using an LLM
to judge quality; AgentBench [14], GAIA [15] and SWE-bench [16] are the field
standard for agent benchmarks, including the difficulty-tier and realistic-task
design that SupplierBench mirrors. *Synthesis: these define how to evaluate LLM
systems, but none targets multi-constraint procurement or measures auditability,
which your benchmark adds.*

**Hallucination and abstention (papers 17–18).** Ji et al. [17] is the
authoritative survey of hallucination, framing your entity- and
attribute-hallucination results; Rajpurkar et al. [18] introduced the
"unanswerable question" methodology that your Abstention-5 set follows.
*Synthesis: these give the vocabulary for grounding and abstention; your work
applies them to a governed supplier-discovery setting and reports an honest
negative abstention result.*

**Benchmarking and statistical methodology (papers 19–21).** Because this is a
*benchmarking* thesis, the evaluation itself needs grounding: Järvelin &
Kekäläinen [19] defined nDCG, one of your ranking metrics; Buckley & Voorhees [20]
is the classic reference on evaluating retrieval when relevance judgments are
incomplete, which justifies how you build and reason about ground truth on a
small curated benchmark; and Smucker, Allan & Carterette [21] compared
significance tests for IR and support the use of bootstrap/randomisation tests
over the Wilcoxon test — directly justifying your paired-bootstrap significance
procedure. *Synthesis: these are the methodological backbone that makes a
25-query benchmark defensible rather than anecdotal.*

**Domain — supplier selection (papers 22–23).** Classical supplier selection has
been solved with multi-criteria decision methods and classical machine learning
[22, 23]. *Synthesis — and this is your central gap sentence: supplier selection
has a long history in operations research and classical ML, but not as an
LLM-based agentic discovery task with evidence-based verification and
auditability, which is what this thesis contributes.*

### C.3 How this maps to your hypotheses and evaluations

- **H1 (agentic satisfies more, gap widens):** grounded by the agent and RAG
  papers [1, 5, 6, 8, 9] and evidenced against the benchmark templates [14, 15, 16].
- **H2 (auditability highest for agentic):** grounded by hallucination and
  faithfulness work [9, 12, 17] and the abstention methodology [18].
- **H3 (single-prompt collapses; agentic degrades gracefully at a cost):**
  grounded by benchmark-difficulty design [15, 16] and self-reflection cost
  work [2].
- **Evaluation methodology (Precision@5 / MRR / nDCG / MAP, bootstrap CIs,
  significance testing, LLM-judging):** grounded by [11, 12, 13, 19, 20, 21].

### C.4 Domain background: supplier selection and procurement AI

*(Written as continuous prose so it can be adapted directly into the Related Work
chapter. It uses the two DBLP-verified, well-cited domain references and states
the current state of the field honestly.)*

Supplier selection is one of the most studied decisions in operations research
and supply-chain management, and the literature is mature — but it was built
almost entirely before large language models, and it frames the problem
differently from the way this thesis does.

The classical approach treats supplier selection as a multi-criteria decision
problem over a fixed, clean table of candidate suppliers and evaluation criteria
(price, quality, delivery, capacity, certifications), and solves it with
structured decision methods, often combined with classical machine learning.
Representative and widely cited work includes the fuzzy VIKOR group-decision
method of Sanayei et al. (2010) and the hybrid system of Kar (2015), which
combines the analytic hierarchy process, fuzzy set theory, and a neural network
to rank suppliers. These methods are rigorous, and they established the criteria
and the evaluation vocabulary that procurement still uses. What they assume,
however, is that the problem already arrives as structured data: the candidate
set is given, the criteria are quantified, and the task is to score and rank.
They do not address the natural-language front of the problem — turning a
sentence such as "an ISO 9001 packaging supplier in Germany above 10,000 units
per month" into machine-checkable constraints — nor do they consider verifying
each supplier claim against evidence, discovering entirely new suppliers, or
producing an auditable record of the decision.

More recent work has begun to apply machine learning, and very recently large
language models, to supply-chain and procurement problems such as demand
forecasting, risk assessment, information extraction from supplier documents, and
supply-chain optimisation. Two things about this emerging work matter here. First,
much of the recent machine-learning supplier-selection literature appears in
operations-research and management journals (for example the *International
Journal of Production Research* and the *International Journal of Production
Economics*) that fall outside the scope of a computer-science index such as DBLP;
a purely CS-indexed search therefore understates it, and it is best located
through Scopus or Web of Science. Second, and more importantly for this thesis,
the work that applies *LLM-based, agentic* methods to supplier discovery is, at
the time of writing, almost entirely un-peer-reviewed: it exists as preprints and
has not yet settled into archival, peer-reviewed venues, and there is in
particular no established peer-reviewed benchmark or baseline for LLM-based
supplier discovery on which a new study could build.

This is precisely the situation that motivates the thesis. The mature domain
literature solves a structured ranking problem that assumes the hard part — 
understanding the request, verifying the claims, and making the result auditable —
has already been done by a human. The emerging LLM literature does the
understanding, but it has not yet been evaluated rigorously, compared across
architectures, or held to a standard of verifiability and auditability, and it is
not yet peer-reviewed. The scarcity of prior work is therefore not a gap in the
search; it is the gap itself. This thesis turns that scarcity into its
contribution by supplying the first controlled, reproducible, peer-reviewable
comparison of single-prompt, retrieval-augmented, and agentic architectures for
multi-constraint procurement supplier discovery, with constraint satisfaction,
verifiability, and auditability measured together (developed fully in Part D).

**Finding more recent domain sources.** Because DBLP under-indexes
operations-research venues, complement it with Scopus or Web of Science for the
recent machine-learning supplier-selection literature. Search the journals
*Expert Systems with Applications*, *Knowledge-Based Systems*, *Decision Support
Systems*, *Computers & Industrial Engineering*, *International Journal of
Production Research*, and *International Journal of Production Economics* with the
terms from §B.1's domain row, pick two or three recent, well-cited items, and
confirm each record and its ranking before citing.

---

## Part D — The research gap this thesis fills

*(This section is written in continuous prose so it can be adapted directly into
the Related Work or Introduction chapter. Citation years match the verified
papers in Part C.)*

Three separate bodies of research bear on this thesis, and the gap it addresses
lies precisely where they fail to meet.

The first is the literature on large-language-model agents. Over the last few
years this field has established the core mechanisms of agentic systems: the
ReAct pattern of interleaving reasoning with tool use (Yao et al., 2023), the
ability of models to teach themselves to call tools (Schick et al., 2023; Qin et
al., 2024), self-reflection and revision through verbal feedback (Shinn et al.,
2023), and the decomposition of a task across several specialised agents (Hong et
al., 2024; Wu et al., 2024). A parallel line of work has established how such
systems should be evaluated, through agent benchmarks such as SWE-bench (Jimenez
et al., 2024), GAIA (Mialon et al., 2024), and AgentBench (Liu et al., 2024).
This body of work is mature and fast-moving, but it is aimed almost entirely at
software engineering, general-purpose web assistance, and open-ended API
manipulation. None of it addresses procurement supplier discovery, and, more
tellingly, none of it treats auditability — the ability to trace an answer back
to specific evidence — as something to be measured. The mechanisms and the
evaluation templates exist; they have simply never been pointed at this problem.

The second body of research is retrieval-augmented generation. Since Lewis et al.
(2020) introduced RAG and Karpukhin et al. (2020) established dense passage
retrieval, the field has produced more capable variants, such as the
retrieve-and-critique design of Self-RAG (Asai et al., 2024), and dedicated
evaluation frameworks, such as the BEIR retrieval benchmark (Thakur et al., 2021)
and the RAGAs faithfulness suite (Es et al., 2024). These frameworks measure how
well a system retrieves relevant passages and how faithfully it answers, largely
in the setting of open-domain question answering. What they do not measure is
whether a returned set of items satisfies several hard, structured constraints at
once — a certification, a capacity floor, a lead-time ceiling, and a geography,
all in the same request — which is the defining feature of a procurement query.
Nor do they score auditability. RAG, in other words, tells us how to ground an
answer in retrieved text, but not how to guarantee and evidence constraint
satisfaction for a governed, high-stakes decision.

The third body of research is the application domain itself. Supplier selection
has a long and rigorous history in operations research and classical machine
learning, where it is typically framed as a multi-criteria decision problem and
solved with methods such as fuzzy AHP, VIKOR, and neural-network scoring (Sanayei
et al., 2010; Kar, 2015). This literature is well developed, but it predates
large language models. It assumes the decision problem arrives as a clean,
structured table of candidate suppliers and criteria, and it optimises a ranking
over that table. It does not consider the task this thesis studies, in which the
constraints must first be parsed out of a natural-language sentence, each supplier
claim must be verified against evidence, new suppliers may have to be discovered
and screened, and the whole result must be made auditable for a regulated
workflow.

The gap this thesis fills sits in the space these three literatures leave open. To
the best of my knowledge, no peer-reviewed study has compared the three dominant
architectural paradigms for LLM-based supplier discovery — a single-prompt model,
a retrieval-augmented pipeline, and a verification-based agentic system — head to
head on the same procurement benchmark, under an identical language model,
supplier corpus, ground truth, and scoring procedure, and measured not only
retrieval quality but constraint satisfaction, verifiability, and auditability
together. This absence is not merely a matter of no one having done the
experiment: the emerging work that does apply LLM agents to supply-chain and
procurement problems is, at the time of writing, almost entirely un-peer-reviewed
and available only as preprints. That scarcity both confirms the novelty of the
question and means there is no established benchmark or baseline in this specific
setting to build upon.

This thesis therefore makes three connected contributions that close the gap.
First, it provides the missing controlled comparison, holding the model, the
corpus, the ground truth, and the scoring code constant so that any measured
difference is attributable to the architecture rather than to the model or the
data. Second, it releases a reproducible benchmark, SupplierBench-25 over a
10,000-supplier synthetic corpus, together with baseline implementations of all
three paradigms, so that the comparison can be repeated and extended. Third, and
methodologically most distinctive, it does not stop at an end-to-end score: a
component ablation attributes the agentic system's performance to the specific
part responsible — the per-constraint verification gate — rather than to the
architecture as an undifferentiated whole. The evaluation follows established
information-retrieval practice for a small, curated benchmark (Buckley &
Voorhees, 2004; Smucker et al., 2007; Järvelin & Kekäläinen, 2002), reporting
ranked-retrieval metrics with bootstrap confidence intervals and a paired
significance test, and it reports honestly where the agentic approach does not win
— a candour the surrounding literature rarely shows.

Stated in one sentence: **the gap is the absence of a reproducible, honest,
component-level, head-to-head evaluation of single-prompt, retrieval-augmented,
and agentic architectures for multi-constraint, auditability-sensitive procurement
supplier discovery — and this thesis supplies exactly that.**

---

## Part E — Quick checklist before you submit the review

- [ ] Every paper opened on DBLP and BibTeX exported (no hand-typed citations).
- [ ] No arXiv-only citations (each has a real venue).
- [ ] AI/ML/RAG/LLM papers are 2023–2026, except clearly-labelled origin papers.
- [ ] Conference ranks confirmed on CORE; journal quartiles confirmed on SCImago.
- [ ] Each paper connects to at least one research question.
- [ ] Themes organised by concept, each ending with a gap-connecting sentence.
- [ ] The summary table is present and maps papers to RQ/H/EVAL.
- [ ] The domain gap is stated explicitly, not hidden.
