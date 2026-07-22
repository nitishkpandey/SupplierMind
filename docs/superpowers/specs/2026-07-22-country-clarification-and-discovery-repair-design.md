# Country Clarification and Discovery Repair Design

**Date:** 2026-07-22

## Objective

Make interactive country-only procurement requests pause for a delivery city,
region, or radius before supplier discovery unless the user explicitly requests
a country-wide search. Fixed-corpus benchmark evaluation bypasses this
interactive gate and deterministically treats its country constraint as the
intended nationwide scope. After that behavior is proven, improve parser
efficiency and web-query relevance in a separate change so valid web suppliers
can reach the existing strict compliance pipeline.

The work targets the production failure observed for:

> I want to buy 1000 (.5l) bottles of Helles and Pilsner beer in Germany for a
> client summer party.

The fix must remain generic. No product-specific or brewery-specific exception
will be added to parser, discovery, compliance, or ranking code.

## Confirmed Root Causes

1. The Parser exhausted all six ReAct iterations after repeatedly calling the
   quantity parser, then recovered usable product and country constraints via
   its degraded fallback.
2. Deterministic clarification runs only after a clean `Finish`. Degraded
   `max_iterations` runs bypass it, and the orchestrator deliberately refuses
   to persist their clarification state.
3. Product plus country is currently considered sufficient on that degraded
   path. The pipeline therefore started discovery without asking where in
   Germany delivery or proximity mattered.
4. The local supplier corpus contains no beer or brewery suppliers. Correct
   results for this query therefore depend on web discovery.
5. Web search concatenated overlapping product phrases into keyword-stuffed
   queries. Tavily returned four informational pages and one UK brewery. The
   classifier correctly rejected the articles, and location validation
   correctly rejected the UK supplier against Germany.
6. Compliance correctly rejected the ten unrelated semantic fallback
   candidates. Strict product and location enforcement is not the defect and
   must not be weakened.

## Operational Baseline

`/Users/nitishkumarpandey/Desktop/SupplierMind` is the only canonical workspace
for `production/agentic-suppliermind`. The former
`/Users/nitishkumarpandey/Desktop/SupplierMind-production` linked worktree was
clean and has been removed. Other remaining worktrees use different branches.
The previously local TypeScript strict-mode commit has been pushed to
`origin/production/agentic-suppliermind`.

## Chosen Sequence

Implementation is split into two independently tested and committed phases.
Phase 2 starts only after Phase 1 passes its focused and regression tests.

### Phase 1: Deterministic country-scope clarification

Add one deterministic gate after constraint normalization and before discovery.
It applies regardless of whether ReAct terminated through `Finish`,
`max_iterations`, or another recoverable degraded path.

The gate pauses when all of the following are true:

- a usable product or service is present;
- `location_country` is present;
- `location_city`, `location_region`, and `location_radius_km` are absent; and
- the current user text does not explicitly request a country-wide search; and
- `benchmark_supplier_ids` is empty, meaning this is an interactive production
  query rather than a fixed-corpus evaluation run.

Only `location_city`, `location_region`, and `location_radius_km` satisfy the
scope requirement. `location_lat`, `location_lng`, and `location_bounds` do not.
Geocoding a country can populate its centroid and national bounding box; those
artifacts must never make a country-only query appear locally scoped.

The question will ask for one decision in one sentence:

> Which city or region should I search near, or should I search all of Germany?

The country name is taken from parsed constraints rather than hard-coded.

Explicit country-wide intent includes phrases such as `country-wide`,
`nationwide`, `throughout Germany`, `all of Germany`, or `anywhere in Germany`.
Equivalent constructions using another parsed country must work as well.
Existing global/unbounded phrases remain supported, but country-wide intent is
distinct from a worldwide search: it retains `location_country` as a hard
constraint.

Country-wide intent detection is one small pure function with focused positive
and negative tests. A missed wording causes one clarification question rather
than silently widening or narrowing the search.

#### Fixed-corpus evaluation bypass

SupplierBench evaluation calls `run_pipeline` once with
`benchmark_supplier_ids` and has no interactive clarification loop. When that
list is non-empty, the country-scope gate is bypassed deterministically and the
parsed country remains a hard constraint. No evaluation-runner changes and no
benchmark-query text exceptions are introduced.

The bypass applies on clean and degraded parser terminations and suppresses the
existing country-only `operational_preference` clarification as well as the new
country-scope question. Other malformed benchmark input may still fail through
the normal error path; evaluation is not given a general clarification bypass.

This bypass applies only to fixed-corpus evaluation. Normal `approved_only` and
`both` searches remain interactive and must satisfy the gate.

When the gate fires:

- `needs_clarification` and `pipeline_status` are set before the graph can route
  to external or internal discovery;
- the normalized partial constraints and ReAct trace are persisted even if the
  parser terminated through a degraded path;
- the API emits the existing resumable `needs_clarification` event; and
- no discovery, compliance, ranking, or evaluator stage runs on that turn.

On resume, the existing clarification flow merges the answer with the original
query and partial constraints. A city, region, or radius answer continues into
discovery. An explicit country-wide answer also continues, retains the country
filter, and does not re-ask the same question.

If the first answer still supplies neither local scope nor explicit
country-wide intent, the gate asks the same scope decision once more. If the
second answer is still unusable, the third parser turn proceeds country-wide
while retaining `location_country`. The implementation uses the existing
`turn_number` and `MAX_CLARIFICATION_TURNS = 3` boundary from
`clarification_repo`; it does not add a second counter or permit an unbounded
re-ask loop. In concrete terms:

- turn 1 may raise the initial country-scope clarification;
- turn 2 may raise one re-ask; and
- turn 3 fails open to country-wide scope and continues discovery.

This rule intentionally changes country-only behavior. A user who genuinely
wants a nationwide search can state that in the original query or select it in
the clarification response.

### Phase 2: Parser and web-discovery quality

Phase 2 is a separate commit with no relaxation of compliance rules.

#### Quantity-tool discipline

Buyer order quantities such as `1000 bottles` are demand context, not supplier
capacity. The Parser prompt and deterministic tool-use guard will prevent
`parse_quantity_unit` calls unless the text contains an explicit supplier
capacity or rate signal such as `capacity`, `throughput`, or `per month`.

Existing normalization continues clearing any buyer quantity accidentally
placed in `capacity_min` or `capacity_unit`. This phase does not introduce a new
order-quantity schema or capacity compliance behavior.

#### Compact Tavily queries

Web discovery will stop joining the product type and every overlapping keyword
into one repeated phrase. It will:

- normalize and deduplicate overlapping product terms;
- keep the clearest product phrase plus a small number of distinctive variants;
- include the parsed industry context when available; and
- run compact manufacturer/distributor/wholesaler query variants before applying
  the global result cap.

The change remains language-neutral in this phase. German-language supplier
vocabulary and query translation are explicitly deferred.

## Deferred Work

The following changes are outside these two commits:

- German-language or country-specific query families;
- richer audit diagnostics for country conflict versus unverifiable location;
- a new structured buyer-order quantity schema;
- an intent-planning architecture rewrite; and
- weakening product, location, sanctions, certification, capacity, or lead-time
  compliance.

They should be reconsidered only if Phase 2 still cannot retrieve relevant web
candidates in the live E2E test.

## Demo Data Insurance

Because the internal corpus has no brewery suppliers, a live web-only demo is
inherently dependent on Tavily, source-page availability, extraction, and
Geoapify. A small set of real, source-cited German brewery suppliers may be
seeded as separate demo data after the two code phases are verified.

Demo seed data must:

- use an explicit demo/manual provenance;
- remain separate from SupplierBench fixtures and generation scripts;
- never modify or regenerate the frozen benchmark corpus; and
- be idempotent and removable without affecting benchmark evaluation.

Creating demo seed data is not part of Phase 1 or Phase 2 and requires a
separate decision after the code fixes are validated.

## Testing Strategy

Implementation follows red-green-refactor.

Phase 1 tests cover:

- a clean `Finish` with product plus country pauses for clarification;
- a `max_iterations` fallback with product plus country also pauses;
- degraded clarification state is persisted and receives an ID;
- parser output cannot route to any discovery stage while paused;
- a city, region, and radius response each resume successfully;
- a country-wide response resumes without dropping the country constraint;
- explicit nationwide intent in the original query bypasses clarification; and
- a fixed-corpus evaluation run with a country-only query does not pause;
- country centroid latitude/longitude and national bounds do not satisfy the
  scope requirement;
- one unusable answer re-asks, while a second unusable answer proceeds
  country-wide on the existing final turn; and
- missing-product clarification behavior remains unchanged.

Phase 2 tests cover:

- buyer order quantities do not invoke or populate supplier-capacity parsing;
- explicit per-period capacity still invokes and populates capacity parsing;
- overlapping product terms compile into compact, non-repetitive queries;
- industry context participates in relevant query variants;
- all query families run before the final result cap; and
- existing strict location and product compliance tests remain green.

Verification after each phase includes focused unit tests, the full backend test
suite, Ruff, and mypy. Phase 2 additionally runs the exact Helles/Pilsner query
through the live `both` scope after answering the location clarification.

## Acceptance Criteria

### Phase 1

- The reproduced Helles/Pilsner query stops before discovery and asks for a
  city, region, or all-Germany choice.
- The same behavior occurs whether ReAct finishes cleanly or exhausts its
  iteration budget.
- The rule applies to every product and country combination; no beer, brewery,
  Germany, or benchmark-query string is hard-coded.
- Answering `Munich`, `Bavaria`, or an explicit radius resumes the existing
  query with the prior product and country constraints intact.
- Answering `all of Germany` resumes once and keeps Germany as a hard country
  constraint.
- Country centroid coordinates and country bounds do not suppress the question.
- One unusable answer causes one re-ask; a second unusable answer proceeds
  country-wide on turn 3 without dropping the country constraint.
- SupplierBench runs with non-empty `benchmark_supplier_ids` never pause for
  country scope and preserve the frozen benchmark execution contract.
- For an interactive run that pauses, no external API or supplier search runs
  before the clarification is resolved or the final-turn country-wide fallback
  is reached.

### Phase 2

- The reproduced query no longer spends repeated ReAct iterations parsing
  `1000 bottles` as supplier capacity.
- Tavily receives compact, distinct queries instead of repeated product-keyword
  soup.
- Relevant German candidates can reach extraction and strict location
  validation when the search provider returns them.
- Unrelated or wrong-country candidates continue to fail compliance or
  validation.
