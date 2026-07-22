# Thesis Evaluation Protocol

This protocol separates scientific benchmark evaluation from live production
validation. Both use the same system, but they answer different questions.

## 1. Research questions

1. Does the agentic system improve supplier retrieval quality over the P1 and P2
   baselines?
2. Does each agent/tool contribute measurably to correctness?
3. What error categories remain, where do they enter the pipeline, and how far
   do they propagate?
4. What quality, latency, and cost trade-offs result from the agentic design?

Define the hypotheses, primary metrics, and decision thresholds before running
the final benchmark. Treat later exploratory analysis as exploratory.

## 2. Two evaluation tracks

### Track A: frozen thesis benchmark

Use the committed SupplierBench corpus and query set. Freeze the commit, model,
prompt versions, tool configuration, corpus version, temperature, random seed
where supported, and evaluation code. Compare P1, P2, and P3 on the same inputs
and ground truth.

This track supports causal comparison, reproducibility, confidence intervals,
and thesis claims.

### Track B: live production validation

Use real APIs and the frontend-to-backend path. Measure authentication, HTTP and
SSE behavior, external-source availability, latency, timeouts, error messages,
CSV output, observability, and graceful degradation.

This track supports operational-readiness claims. It must not replace the frozen
benchmark because live web results and third-party services change over time.

## 3. Experimental unit and manifest

One experimental unit is one query, one system configuration, and one repeated
run. Every run should record:

- run ID, UTC timestamp, Git commit, branch, environment, and corpus hash;
- query ID and exact input text;
- paradigm and ablation configuration;
- model and embedding versions, prompts, temperature, and seed if available;
- enabled tools, tool arguments, observable tool results, retries, and fallbacks;
- stage and end-to-end latency, token usage, API cost, and terminal status;
- ranked output, evidence URLs/quotes, constraint verdicts, and evaluator verdict;
- scorer version, annotator decisions, error labels, and notes.

Do not attempt to score private chain-of-thought. Score observable behavior:
actions, tool selection, arguments, state transitions, evidence, and outputs.

## 4. Primary metrics

Report macro averages across queries as the primary view so large result sets do
not dominate the study. Include per-tier results and paired confidence intervals.

| Dimension | Recommended measures |
|---|---|
| Retrieval | Precision@k, Recall@k, F1@k, nDCG@k, zero-result accuracy |
| Constraints | Hard-constraint satisfaction rate, per-constraint precision/recall |
| Grounding | Evidence coverage, unsupported-claim rate, citation correctness |
| Agent behavior | Correct tool choice, valid arguments, successful tool completion, appropriate clarification rate |
| Reliability | Completion rate, timeout rate, retry rate, graceful-degradation rate |
| Efficiency | End-to-end and per-stage p50/p95 latency, tokens, external calls, cost |

For supplier discovery, precision and hard-constraint satisfaction should be
treated as safety-critical: returning an incompatible supplier is usually worse
than an honestly explained zero result.

## 5. Error taxonomy and blast radius

Label both the first incorrect stage and the final user-visible effect.

| Category | Example | Typical downstream effect |
|---|---|---|
| Intent parsing | Product, location, unit, or certification misread | Wrong search space and compliance checks |
| Retrieval | Relevant supplier missed or irrelevant supplier retrieved | False negative or added validation load |
| Tool use | Wrong tool, malformed argument, timeout, or unavailable service | Missing or stale evidence |
| Entity resolution | Supplier/site/location linked incorrectly | Evidence attached to the wrong company |
| Evidence extraction | Unsupported certification or delivery claim | False positive compliance verdict |
| Constraint logic | Unit, radius, deadline, or category compared incorrectly | Incorrect pass/fail decision |
| Ranking | Correct candidate ranked below weaker candidates | Lower Precision@k/nDCG |
| Orchestration | Retry, fallback, or deadline handled incorrectly | Partial or failed run |
| API/UI contract | Backend state represented incorrectly in UI/CSV | Misleading user-visible result |

Record blast radius as: affected stage, affected constraints, affected suppliers,
affected queries, whether the error changes rank/acceptance, and whether it is
visible to the user. Maintain a regression query for every confirmed bug.

## 6. Ablation study

Use the full P3 system as the control. Change one factor at a time:

1. no external web discovery;
2. no query memory;
3. no deterministic compliance short-circuit;
4. no evaluator/retry loop;
5. no geocoding/radius enforcement;
6. no certification normalization;
7. no deadline-aware budgeting;
8. LLM-only versus deterministic-plus-LLM constraint evaluation.

Run every ablation on the identical frozen query set and paired run schedule.
Report the metric delta, paired 95% confidence interval, latency/cost delta, and
new error categories. An ablation is informative even when it improves one
metric and harms another.

## 7. Repetition and statistics

- Run deterministic baselines once after confirming reproducibility.
- Run stochastic configurations at least five times per query/configuration, or
  justify a different count with a power or stability analysis.
- Use paired bootstrap confidence intervals for retrieval metric deltas.
- Use McNemar's test for paired binary correctness and a paired permutation or
  Wilcoxon test for non-normal latency/quality differences.
- Report effect sizes and confidence intervals, not only p-values.
- Correct for multiple comparisons when drawing conclusions from many ablations.

## 8. Human scoring and correctness

Create a written rubric before annotation. Blind annotators to the paradigm when
possible. Double-annotate a representative subset, report agreement (Cohen's
kappa or Krippendorff's alpha), adjudicate disagreements, and preserve both raw
labels and adjudicated labels.

For each returned supplier, score product relevance, location, every requested
hard constraint, evidence support, and overall acceptability. For zero results,
score whether the corpus truly contains no valid supplier and whether the system
explains the limiting constraints accurately.

## 9. Correctness gate per benchmark query

A query passes only when:

1. the expected interaction state is correct (answer or clarification);
2. every returned supplier matches the requested product/category;
3. every hard-constraint pass is supported by evidence;
4. no known valid supplier is omitted beyond the declared recall tolerance;
5. output ordering and scores follow the published rubric;
6. failures, partial results, and zero results are represented honestly;
7. the run stays within its declared time and cost budget.

## 10. Reporting template

For each experiment, publish:

1. research question and preregistered hypothesis;
2. independent/dependent variables and controlled variables;
3. dataset, sample size, repetition count, and manifest;
4. aggregate metrics with confidence intervals;
5. per-query results and error-category counts;
6. latency/cost distributions and failure rates;
7. ablation deltas and blast-radius analysis;
8. threats to validity and reproducibility instructions;
9. conclusion limited to the evidence collected.

The thesis should use Track A for its central comparative claims and Track B as
an external-validity and engineering-readiness study.
