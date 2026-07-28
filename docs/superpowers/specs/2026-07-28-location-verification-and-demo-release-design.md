# Location Verification and Demo Release Design

Date: 2026-07-28  
Target branch: `production/agentic-suppliermind`  
Release target: `main`

## Goal

Make supplier discovery reliable for generic procurement queries while preserving strict
location compliance, provide a source-cited internal-search floor for the live German beer
demo, verify the UI-to-backend clarification/resume flow, and release the verified work to
`main`.

The `thesis-experiments` branch and the frozen SupplierBench corpus must remain untouched.

## Evidence and Root Cause

An instrumented live run used the original order with the clarified scope of Munich,
Germany. Tavily returned six pages:

- Four were correctly rejected before extraction because they were trade-fair, directory,
  or editorial pages.
- Paulaner passed location validation. Its source page identified Munich, and Geoapify
  resolved Munich with geocoding confidence `1.0`.
- Woove passed Stage 1 as `Woove Beer`, but Stage 2 renamed it to the generic page title
  `Beer Wholesale Germany`. Geoapify then resolved only the query context, Munich, with
  confidence `0.25`; the company-name check also failed. The Places lookup returned no
  feature.

The run establishes three separate facts:

1. Location validation is not universally failing.
2. The Stage-1 company identity is discarded before Stage 2, which can create an invalid
   geocoding query.
3. The Places path uses the Geocoding-only `rank.confidence` contract. Missing confidence is
   converted to `0.0`, so otherwise valid Places features cannot pass the shared `0.6`
   threshold.

The third issue did not reject Woove in this run because Places returned no feature, but it is
a deterministic schema mismatch in the generic fallback path.

## Scope

### 1. Preserve supplier identity across extraction stages

`SupplierExtractionService.stage2_extract` will accept an optional Stage-1 company-name hint.
`ExternalDiscoveryAgent` will pass `classification["company_name"]` into Stage 2.

The hint is evidence, not an unconditional override:

- It is included in the Stage-2 extraction prompt as a candidate identity.
- The model must still extract facts from the fetched supplier page.
- A deterministic fallback may use the hint only when the hint appears in fetched source
  text and the extracted name is missing or is a generic page/category title.
- An unverified hint must never replace a source-supported company name.

This behavior is product-agnostic and applies to all supplier categories.

### 2. Use source-specific Geoapify validation

Geocoding and Places have different response contracts and will be validated separately.

Geocoding remains fail-closed:

- A feature must contain city, country, and coordinates.
- A company-context query must match the expected supplier name.
- `rank.confidence` must be numeric and at least the configured threshold, currently `0.6`.
- Country and city/radius constraints remain hard filters.

Places validation will not invent or require Geocoding confidence:

- A feature must contain city, country, and coordinates.
- It must match the requested supplier name.
- It must match the requested country and city/region/radius constraints.
- If Places supplies a numeric confidence, it may be retained as metadata, but missing
  `rank.confidence` is not itself a rejection.
- The resulting `VerifiedLocation.confidence` is nullable so absence is represented honestly,
  rather than as `0.0` or a fabricated high value.

The configured Geocoding threshold will not be lowered or reverted.

### 3. Keep location evidence honest

Stage 2 will request and preserve a location citation from the main supplier page when city,
country, or address is extracted there. Existing same-site contact, `Kontakt`, `Impressum`,
and imprint probes remain available when the main page has no usable location.

A city-only Geocoding result verifies coordinates for the cited supplier locality; it must not
be presented as a street address. Supplier-name validation remains mandatory when the
location came only from query context rather than cited page content.

### 4. Expose useful generic rejection diagnostics

External discovery will aggregate bounded, non-secret location rejection reasons, such as:

- no geocoding feature;
- supplier-name mismatch;
- missing city/country/coordinates;
- geocoding confidence below threshold;
- country conflict;
- city/radius conflict;
- no Places feature.

The audit summary will retain counts rather than raw page content or external API payloads.
This makes future failures diagnosable without exposing API keys or supplier-page text.

### 5. Add isolated, source-cited demo suppliers

Add an explicit, idempotent demo-seeding command and a separate German brewery fixture.
The records will:

- use real suppliers and official source URLs;
- include only products and locations supported by citations;
- use `source="demo_manual"`;
- be active and approved;
- include a clear approval justification;
- use stable IDs or another deterministic upsert key;
- update both PostgreSQL and the configured vector store;
- never create duplicate rows or duplicate active vectors when re-run.

The seed is an explicit deployment/demo operation. Application startup will not silently
insert demo data.

The fixture and command must not read, write, regenerate, or modify:

- `apps/backend/data/queries_benchmark.json`;
- `apps/backend/data/suppliers_synthetic.json`;
- `apps/backend/data/suppliers_synthetic_10k.json`;
- `apps/backend/data/generate_dataset.py`;
- benchmark result directories or thesis reports;
- the `thesis-experiments` worktree or branch.

Normal benchmark execution remains isolated by `benchmark_supplier_ids`, so approved demo
rows cannot enter SupplierBench evaluation.

## UI and Backend Contract

No UI redesign is required. The existing contract remains:

1. The frontend submits a query to `POST /api/v1/queries`.
2. The result page subscribes to the query SSE stream.
3. A resumable parser pause emits `needs_clarification`.
4. The clarification card submits the answer to
   `POST /api/v1/queries/{query_id}/clarify`.
5. The frontend re-subscribes to the same query stream.
6. The resumed backend pipeline emits progress and a terminal result.

Verification must exercise this contract through the browser, not only through unit tests.
The original country-only beer query must render the location question. Both `Munich` and
`all of Germany` answers must resume the same query successfully.

## Testing Strategy

Implementation follows RED-GREEN-REFACTOR.

Required automated coverage:

- Stage 1 passes a company-name hint into Stage 2.
- A verified Stage-1 hint prevents a generic page title from becoming the supplier name.
- An unverified hint cannot override the extracted supplier name.
- Main-page location citations are preserved.
- Geocoding still rejects missing, non-numeric, and below-threshold confidence.
- Places accepts a complete, name-matching, in-scope feature without
  `rank.confidence`.
- Places rejects name, country, city/radius, or coordinate mismatches.
- Nullable location confidence is serialized and persisted without fabricating certainty.
- Demo seeding is idempotent and uses only `demo_manual` approved records.
- Benchmark allowlisting excludes demo records.
- Existing parser, clarification, compliance, ranking, and evaluation tests remain green.

Release verification:

- full backend test suite;
- Ruff and mypy;
- frontend tests, ESLint, TypeScript/Vite production build, and bundle check;
- benchmark-safety tests;
- local UI/backend browser E2E for clarification and resume;
- live Munich discovery;
- live Germany-wide discovery;
- internal-search result using the demo seed;
- clean Git status and an explicit diff check proving the thesis worktree is unchanged.

## Release and Rollback

Changes are implemented as reviewable commits on `production/agentic-suppliermind`.
After all verification passes:

1. Update the remote production branch.
2. Merge the production branch into local `main`.
3. Re-run release-critical verification on the merged tree.
4. Push `main`.

No force-push, destructive reset, thesis merge, or benchmark regeneration is permitted.

If verification fails after merging locally, do not push `main`; keep the production branch
and local merge available for diagnosis. Demo seed rows can be deactivated by their stable
IDs if rollback is required, without deleting benchmark data.

## Non-Goals

- Replacing the two-stage discovery architecture.
- Relaxing hard location constraints.
- Accepting directories, event pages, or editorial pages as suppliers.
- Adding beer-specific parser or discovery logic.
- Automatically approving future web-discovered suppliers.
- Changing SupplierBench, benchmark metrics, or thesis results.
