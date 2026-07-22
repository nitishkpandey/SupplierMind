# Production Search and UI Hardening Design

**Date:** 2026-07-21

## Objective

Correct every failure or concern in the 21-query production matrix, expose the
backend's decisions accurately in the UI, and replace the development-login
redirect with a direct JSON login flow. The implementation must preserve strict
compliance: SupplierMind must never present an unverified supplier as satisfying
a certification, location, lead-time, or capacity requirement.

## Scope

This change covers:

- adjective-led vague-query clarification;
- geographic radius and region enforcement;
- capacity-unit normalization and dimensional comparison;
- certification-aware web-search diversity for valid `both` searches;
- an end-to-end query deadline below the 155-second client ceiling;
- results/history/API transparency and CSV correctness;
- development login without a redirect or credentials in a URL; and
- automated regression coverage plus a fresh run of the full 21-query matrix.

Google and GitHub OAuth retain their current redirect flow in this pass. Replacing
their token-bearing callback URLs with one-time authorization codes is a separate
security change.

## Root Causes

1. `good` and related quality adjectives are not consistently classified as
   non-product words. The parser can therefore accept `good` as `product_type`,
   bypass clarification, and persist polluted intent into query memory.
2. Discovery combines semantic, structured, fresh-web, and geospatial candidates
   by union. Only candidates returned by the geospatial channel receive a distance,
   so a semantic candidate outside the requested radius can reach compliance with
   no radius verdict.
3. `location_region` exists in parsed state but Supplier records have no region
   field and discovery/compliance do not enforce it.
4. Quantity parsing accepts arbitrary nouns as units. Phrases such as
   `5000 aluminum housings per month` become `aluminumhousings/month`. Compliance
   also treats every unequal unit string as `PARTIAL`, even when the physical
   dimensions are incompatible.
5. Web discovery can fill its global result limit from the first generic query and
   return before running a certification-focused query. Strict office-furniture
   searches therefore may never inspect pages likely to contain certification
   evidence.
6. Parser calls, rate-limit pacing, web search, extraction, location enrichment,
   sanctions screening, and evaluation do not consume one shared deadline. A
   local timeout in one stage cannot prevent the whole query exceeding 155 seconds.
7. The query results response omits stored routing/evaluation fields. The frontend
   consequently uses a fixed progress sequence and a generic zero-results message.
8. Development login is implemented as a GET that issues a `307` redirect with
   access and refresh tokens in the callback URL.

## Chosen Approach

Harden the existing agent pipeline with deterministic boundaries. This is smaller
and safer than replacing the pipeline with a new constraint engine, while avoiding
benchmark-specific query exceptions.

### 1. Intent and clarification

- Maintain one canonical set of supplier-quality adjectives used by placeholder
  detection, product cleanup, keyword recovery, and fallback extraction.
- A product candidate containing no content token after quality, procurement,
  certification, location, and operational words are removed is `None`.
- `good reliable suppliers in Germany` must pause for clarification instead of
  searching.
- Query memory may supply omitted prior product constraints only when the user
  explicitly references prior context. Constraints stated in the current query,
  including `Bavaria`, override recalled values.
- Invalid or adjective-only products are never written back as usable memory.

### 2. Geographic enforcement

- Radius is a hard candidate constraint, not merely an additional ranking channel.
  When a radius and center coordinates are present, every candidate must have
  coordinates and be within the requested radius before compliance and ranking.
- Discovery records distance for every retained radius candidate. Compliance emits
  an explicit `location_radius` verdict for every such result.
- Geocoding returns an optional bounding box for regions. Parsed constraints carry
  that box as `location_bounds: [south, west, north, east]` in decimal degrees.
- When `location_region` is present, candidates must have coordinates inside the
  verified region bounds. Region text is also included in web-search and location
  enrichment context.
- If region bounds cannot be verified, the pipeline returns an explicit diagnostic
  rather than silently ignoring the region.

### 3. Capacity semantics

- Normalize units into a canonical unit and dimension: count, mass, volume, or
  unknown, with an optional period.
- Count-noun phrases such as `aluminum housings per month` normalize to
  `units/month`; product words never become a unit.
- Compatible aliases are compared after normalization. Supported scale conversions
  such as kilograms to metric tons are deterministic.
- Incompatible known dimensions, for example `units/month` versus `kg/month`, are
  `FAIL`; missing/unknown supplier capacity remains `PARTIAL`.
- Purchase quantities without a capacity/throughput signal continue to be excluded
  from supplier-capacity constraints.

### 4. Web discovery and strict evidence

- Build query families for product/location, certification evidence, and category.
- Allocate the result budget across query families before applying the global cap,
  ensuring that a certification-focused query runs when certification is required.
- Deduplicate after merging query-family results, retaining source relevance.
- Carry newly ingested suppliers directly into discovery as today.
- Certification and lead-time evidence remain fail-closed. Improving discovery does
  not convert missing evidence into a pass.

### 5. Deadline and partial completion

- Add a configurable end-to-end execution budget of 145 seconds, leaving ten
  seconds below the existing 155-second matrix client ceiling.
- Store a monotonic deadline in pipeline state and pass remaining time to every LLM
  and external HTTP call.
- Rate-limit acquisition accepts a maximum wait. If pacing would exhaust the
  remaining budget, it raises a typed budget exception instead of sleeping beyond
  the deadline.
- Agents check remaining budget before starting another tool call or candidate.
- If time expires after verified candidates exist, finish with those candidates and
  mark diagnostics as partial. If none exist, finish with a clear timeout diagnostic.
- The query record reaches a terminal state and the SSE stream sends one terminal
  event before the frontend timeout.

### 6. API and frontend transparency

The query results response adds:

- `search_scope`;
- `evaluator_retries`;
- `evaluator_verdict`; and
- a structured `diagnostics` object describing hard constraints, whether external
  discovery ran, deadline/partial status, and a deterministic zero-result reason.

The frontend will:

- show the actual search scope and evaluator outcome;
- omit External Discovery from progress for approved-only searches;
- explain zero results using backend diagnostics, including the hard constraints
  that eliminated candidates;
- render unresolved pending clarifications as `Needs clarification` in History;
- use accurate history response types;
- label `constraint_score` as `Constraint Score` in CSV; and
- escape every CSV field consistently.

Query ownership remains unchanged. Test runs made with a development admin token do
not appear in a different Google user's history.

### 7. Development login

- Replace `GET /auth/dev-login` with `POST /auth/dev-login` in development.
- Return a dedicated `DevLoginResponse` JSON payload containing `access_token`,
  `refresh_token`, `expires_in`, `user_id`, `email`, `name`, and `role`.
- The Login page calls the endpoint, stores the refresh token in session storage,
  sets the access token/user in the auth store, and navigates directly to Dashboard.
- Production continues to return 404 for the development endpoint.
- The development flow no longer returns `307` and no longer places tokens in a URL.

## Error Handling and Diagnostics

- Invalid region bounds, deadline exhaustion, unavailable web search, rejected web
  candidates, and compliance elimination use stable machine-readable diagnostic
  codes plus user-facing text.
- A completed zero-result query is distinct from an infrastructure failure.
- Audit entries retain stage counts and reasons; the results page presents a concise
  explanation and leaves the full evidence in Agent Audit Trail.
- No exception message exposes credentials or API tokens.

## Testing Strategy

Implementation follows red-green-refactor for each behavior.

Backend unit/API tests cover:

- adjective-only products and memory override behavior;
- hard radius intersection and distance verdict completeness;
- Bavaria region bounds and unverifiable-region behavior;
- count-unit cleanup, compatible conversion, dimensional mismatch, and order-quantity
  preservation;
- web-search budget diversity and office-furniture certification queries;
- deadline-aware rate limiting and external stages;
- query response diagnostics and virtual clarification history status; and
- JSON development login plus the production 404 gate.

Frontend tests cover:

- scope-aware progress steps;
- zero-result diagnostics;
- clarification history status;
- CSV headers and escaping; and
- direct development login success and error handling.

Final verification includes backend tests, frontend tests, lint, production build,
and a sequential 21-query E2E rerun under one account. Results are compared against
the original matrix. The run must complete without a query exceeding 155 seconds.

## Acceptance Criteria

- Query 12 asks for clarification and cannot persist `good` as a product.
- Query 6 returns only suppliers within 100 km of Berlin or an honest zero result.
- Query 15 enforces Bavaria and does not return out-of-region suppliers.
- Queries 4 and 9 have canonical, dimension-aware capacity verdicts.
- Query 21 executes certification-focused web discovery and returns only verified
  strict matches; any zero result explains the elimination path.
- Queries 19 and 20 reach a terminal response within 155 seconds.
- The UI displays actual scope, diagnostics, clarification state, and correct CSV
  semantics.
- Development login succeeds through JSON without a `307` response or URL tokens.
- Existing certification, sanctions, approval, and ownership regression tests remain
  green.
