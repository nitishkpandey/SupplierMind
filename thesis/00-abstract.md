# Abstract

Procurement teams spend a great deal of their time looking for suppliers that
must satisfy several requirements at the same time. A single sourcing request,
such as *"an ISO 9001 certified packaging supplier in Germany with capacity above
10,000 units per month and lead time under 30 days"*, stacks four hard
constraints — a certification, a location, a production capacity, and a delivery
window — into one sentence, and an analyst can spend hours filtering candidates by
keyword and reading through their details by hand. Large language models (LLMs)
appear to remove this burden entirely: a buyer can paste the same sentence into a
chat interface and receive a list of suppliers within seconds, and several
procurement-AI products already work in this way. The convenience, however, comes
with a serious cost for decision-making that must be defensible. A plain language
model can invent suppliers, claim certifications that were never issued, and
assert capacity figures that were never stated, and its output is unstructured
prose that cannot be traced back to any source. This matters increasingly under
regulation such as the European Union's AI Act, whose record-keeping obligations
for high-risk systems require that automated decisions be logged and traceable.

This dissertation therefore does not ask whether an LLM can perform supplier
discovery, a question that is already settled, but a harder one: what kind of
architecture *around* a language model makes its output trustworthy enough to use
in a regulated procurement workflow, and what that additional complexity costs in
return. To answer it, the three architectural paradigms that dominate current
practice are compared directly: a single-prompt LLM, a retrieval-augmented
generation (RAG) pipeline (Lewis et al., 2020), and a verification-based agentic
system. The comparison is a controlled benchmarking study: all three run on the
same language model, the same supplier corpus, the same ground-truth labels, and
the same scoring code, so that any difference in the results is attributable to
the architecture rather than to the model or the data. The work was conducted in
collaboration with Mercanis (Cdc3 GmbH), a procurement-technology startup based in
Berlin, Germany, and uses only synthetic supplier data, with no real company or
customer records.

The study is built on SupplierBench-25, a reproducible benchmark of twenty-five
multi-constraint procurement queries across three difficulty tiers over a
10,000-supplier synthetic corpus, together with a five-query abstention set of
deliberately unsatisfiable requests. The agentic system, SupplierMind, is a
five-agent pipeline that parses a query using a ReAct reasoning loop (Yao et al.,
2023), retrieves candidates by combining semantic vector search with structured
constraint filtering, verifies each constraint against quoted evidence, ranks the
survivors deterministically, and records a full audit trail of every decision.
All three paradigms are measured on retrieval quality, constraint satisfaction,
verifiability, and auditability, and the results are reported with bootstrap
confidence intervals and a paired significance test (Smucker, Allan and Carterette, 2007).

The agentic architecture is significantly more precise than RAG, reaching a
Precision@5 of 0.731 against 0.504 (a paired difference of +0.227 with a 95%
confidence interval of [0.126, 0.330]), and its advantage widens as queries stack
more constraints. A component ablation localises this advantage to a single part
of the system, the per-constraint verification gate: with the gate removed, the
agentic pipeline scores below plain RAG, and restoring it raises Precision@5 by
0.305, almost entirely on the hardest queries. The same advantage holds against two
further, independently built RAG baselines — a standard off-the-shelf framework and a
stronger re-ranked pipeline — which both land close to the controlled RAG and well below
the agentic system, confirming that the gain comes from verification rather than from a
weak baseline or a better retriever. The single-prompt baseline returns a supplier that
does not exist in the corpus on every query, even when the request is fully specified. These gains are not free: the agentic system makes roughly
five times as many language-model calls and is several times slower than RAG. The
study also reports an honest negative result — on impossible queries the agentic
system abstains less reliably than RAG, returning near-misses rather than nothing.

The contribution is threefold. First, this is, to the best of my knowledge, the
first controlled, component-level comparison of the single-prompt, RAG, and
agentic paradigms for multi-constraint procurement supplier discovery. Second, it
delivers a public, reproducible benchmark with baseline implementations of all
three paradigms. Third, through the ablation, it provides evidence — rather than
assertion — of exactly where and why the agentic overhead is justified, and where
it is not. As a small methodological addition, the study introduces Verified
Precision@k, which counts a returned supplier only when it is both correct and backed
by verifiable evidence, and on which the agentic system scores 0.731 while RAG scores
0.000 — a single number that captures the difference between a correct answer and a
provable one. The significance of the work is that it reframes supplier discovery
from a naming task, at which a chatbot is already competent, into a
trust-and-governance task, and shows empirically that the verification layer,
rather than retrieval or the agentic scaffolding in general, is what makes the
difference.
