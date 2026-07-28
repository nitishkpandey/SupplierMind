# Production Discovery Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make generic supplier discovery preserve supplier identity, validate Geoapify results according to the correct API contract, expose actionable rejection diagnostics, provide an isolated source-cited demo floor, and verify the complete release from one command before updating `main`.

**Architecture:** Keep the existing two-stage extraction and two-path location service. Add a verified identity hint at the Stage-1/Stage-2 boundary, return immutable location-resolution diagnostics without shared mutable state, seed approved demo suppliers through a separate idempotent service, and orchestrate all automated release checks from a root shell script. Production logic remains category-agnostic; only the explicitly isolated demo fixture contains brewery data.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, LangGraph, Geoapify, PostgreSQL, Milvus, Pytest, Ruff, mypy, React 19, TypeScript, Node test runner, ESLint, Vite, Bash, Docker Compose.

## Global Constraints

- Work on `production/agentic-suppliermind`; update `main` after every independently verified commit.
- Do not modify the `thesis-experiments` worktree or branch.
- Do not modify SupplierBench queries, supplier fixtures, generation scripts, thesis reports, benchmark result files, or benchmark IDs.
- Keep Geocoding fail-closed with `GEOAPIFY_MIN_CONFIDENCE=0.6`.
- Do not add beer-specific branches, parser rules, search queries, compliance rules, or ranking weights.
- Use `source="demo_manual"` only for explicit demo fixtures.
- Use natural, human-written commit subjects without Conventional Commit prefixes.
- Never force-push or rewrite commits already present on a remote branch.
- Every code task must complete its focused RED-GREEN test cycle before its commit is pushed.
- The final release must pass `scripts/verify_release.sh`; live external checks run only with `--live`.

## File Structure

- `apps/backend/app/services/supplier_extraction.py`: supplier identity reconciliation and source-citation extraction.
- `apps/backend/app/services/location_enrichment.py`: source-specific Geoapify validation and immutable diagnostic results.
- `apps/backend/app/agents/external_discovery_agent.py`: pass identity hints and aggregate bounded rejection diagnostics.
- `apps/backend/app/services/demo_seed.py`: validation and idempotent persistence/indexing for explicit demo records.
- `apps/backend/demo/german_breweries.json`: official-source-cited demo records, isolated from benchmark data.
- `apps/backend/scripts/seed_demo_suppliers.py`: explicit demo-seed command.
- `apps/backend/scripts/verify_live_discovery.py`: API-level clarification/resume and result smoke check.
- `scripts/verify_release.sh`: one-command backend, frontend, benchmark-safety, and optional live verification.
- Existing focused test modules: regression coverage close to each production component.

---

### Task 1: Synchronize the Release Branch and Preserve the Thesis Boundary

**Files:**
- Verify only; no production file changes.

**Interfaces:**
- Consumes: `origin/main`, `origin/production/agentic-suppliermind`, local `thesis-experiments`.
- Produces: a release branch containing current `origin/main`, with the thesis branch hash recorded for later comparison.

- [ ] **Step 1: Capture branch and worktree evidence**

Run:

```bash
git fetch origin --prune
git status --short --branch
git worktree list --porcelain
git rev-parse thesis-experiments
git rev-parse origin/main
git rev-parse origin/production/agentic-suppliermind
```

Expected: the active branch is `production/agentic-suppliermind`; the thesis worktree is separate and clean.

- [ ] **Step 2: Merge current main into the release branch**

Run:

```bash
git merge origin/main -m "Bring the current main branch into the production release work"
```

Expected: clean merge or fast-forward. Stop and diagnose any conflict instead of resolving benchmark/thesis files by assumption.

- [ ] **Step 3: Commit the implementation plan**

Run:

```bash
git add -f docs/superpowers/plans/2026-07-28-production-discovery-release.md
git commit -m "Lay out the production discovery release"
```

Expected: one documentation commit with a human-readable subject.

- [ ] **Step 4: Push the synchronized planning state**

Run:

```bash
git push origin production/agentic-suppliermind
git push origin HEAD:main
```

Expected: both remote refs point to the planning commit; no force push is used.

---

### Task 2: Preserve Supplier Identity and Main-Page Location Evidence

**Files:**
- Modify: `apps/backend/app/services/supplier_extraction.py`
- Modify: `apps/backend/app/agents/external_discovery_agent.py`
- Test: `apps/backend/tests/unit/test_supplier_extraction.py`
- Test: `apps/backend/tests/unit/test_discovery_pending_status.py`

**Interfaces:**
- Consumes: `classification["company_name"]` and `classification["confidence"]` from Stage 1.
- Produces: `stage2_extract(url, deadline_at=None, company_name_hint=None) -> dict | None`.
- Produces: `source_citations["location"]` only when its source phrase is present on the fetched page or an existing same-site location probe.

- [ ] **Step 1: Add failing identity-handoff tests**

Add tests equivalent to:

```python
def test_stage2_prefers_verified_high_confidence_company_hint(monkeypatch):
    page = "Woove Beer supplies German beer to wholesale customers."
    monkeypatch.setattr(extraction_module, "fetch_page_content", lambda _url: page)
    service = _service(_payload(name="Beer Wholesale Germany"))

    result = service.stage2_extract(
        "https://woovebeer.example/beer-wholesale-germany",
        company_name_hint="Woove Beer",
    )

    assert result is not None
    assert result["name"] == "Woove Beer"
    assert result["source_citations"]["name"]["source_phrase"] == "Woove Beer"


def test_stage2_does_not_use_company_hint_absent_from_source(monkeypatch):
    page = "Acme Metals GmbH manufactures precision parts."
    monkeypatch.setattr(extraction_module, "fetch_page_content", lambda _url: page)
    service = _service(_payload(name="Acme Metals GmbH"))

    result = service.stage2_extract(
        "https://acme.example",
        company_name_hint="Unrelated Holdings",
    )

    assert result is not None
    assert result["name"] == "Acme Metals GmbH"
```

Add an agent test asserting `stage2_extract` receives the Stage-1 hint only when classification confidence is at least `0.8`.

- [ ] **Step 2: Add a failing main-page location-citation test**

```python
def test_stage2_preserves_verified_main_page_location_citation(monkeypatch):
    page = "Acme Metals GmbH, Werkstraße 4, 80331 Munich, Germany."
    monkeypatch.setattr(extraction_module, "fetch_page_content", lambda _url: page)
    service = _service(
        _payload(
            city="Munich",
            country="Germany",
            address="Werkstraße 4, 80331 Munich, Germany",
            citations={
                "name": "Acme Metals GmbH",
                "location": "Werkstraße 4, 80331 Munich, Germany",
            },
        )
    )

    result = service.stage2_extract("https://acme.example")

    assert result is not None
    assert result["source_citations"]["location"] == {
        "url": "https://acme.example",
        "source_phrase": "Werkstraße 4, 80331 Munich, Germany",
    }
```

- [ ] **Step 3: Run focused tests and confirm RED**

Run:

```bash
cd apps/backend
uv run pytest tests/unit/test_supplier_extraction.py tests/unit/test_discovery_pending_status.py -q
```

Expected: failures show that `company_name_hint` is unsupported, the agent does not pass it, and main-page location citations are dropped.

- [ ] **Step 4: Implement the minimal generic identity contract**

Change the signature to:

```python
def stage2_extract(
    self,
    url: str,
    deadline_at: float | None = None,
    company_name_hint: str | None = None,
) -> dict | None:
```

Append a non-authoritative hint to the Stage-2 user message:

```python
identity_context = ""
if clean_optional_text(company_name_hint):
    identity_context = (
        "\n\nCANDIDATE COMPANY NAME FROM INITIAL CLASSIFICATION: "
        f"{clean_optional_text(company_name_hint)}"
        "\nUse this only if the company name is supported by PAGE CONTENT."
    )
text = (
    f"SOURCE URL: {url}\n\nPAGE CONTENT:\n{full_content[:8000]}"
    f"{identity_context}"
)
```

Add a focused reconciliation helper:

```python
@classmethod
def _reconcile_company_name(
    cls,
    verified: dict,
    company_name_hint: str | None,
    source_text: str,
) -> dict:
    hint = clean_optional_text(company_name_hint)
    if not hint or hint.casefold() not in source_text.casefold():
        return verified
    reconciled = dict(verified)
    extracted = clean_optional_text(reconciled.get("name"))
    if not extracted or extracted.casefold() != hint.casefold():
        reconciled["name"] = hint
        citations = dict(reconciled.get("citations") or {})
        citations["name"] = hint
        reconciled["citations"] = citations
    return reconciled
```

Call it after normalization. Pass the hint from `ExternalDiscoveryAgent` only when
`float(classification.get("confidence") or 0) >= 0.8`.

- [ ] **Step 5: Preserve only source-supported location citations**

Add `"location"` to the Stage-2 prompt citation schema and citation-building loop. Retain it only when the cleaned phrase occurs in fetched page text:

```python
for field in (
    "name",
    "description",
    "location",
    "certifications",
    "capacity",
    "lead_time_days",
):
    source_phrase = clean_optional_text(raw_citations.get(field))
    if not source_phrase:
        continue
    if field == "location" and source_phrase.casefold() not in full_content.casefold():
        continue
    citations_dict[field] = {"url": url, "source_phrase": source_phrase[:300]}
```

Allow the existing same-site discovery evidence to replace the main-page location citation when it provides a more complete address.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run:

```bash
cd apps/backend
uv run pytest tests/unit/test_supplier_extraction.py tests/unit/test_discovery_pending_status.py -q
uv run ruff check app/services/supplier_extraction.py app/agents/external_discovery_agent.py tests/unit/test_supplier_extraction.py tests/unit/test_discovery_pending_status.py
```

Expected: all focused tests pass and Ruff reports no errors.

- [ ] **Step 7: Commit and push immediately**

Run:

```bash
git add apps/backend/app/services/supplier_extraction.py \
  apps/backend/app/agents/external_discovery_agent.py \
  apps/backend/tests/unit/test_supplier_extraction.py \
  apps/backend/tests/unit/test_discovery_pending_status.py
git commit -m "Keep supplier identity intact during web extraction"
git push origin production/agentic-suppliermind
git push origin HEAD:main
```

---

### Task 3: Validate Geoapify Paths Correctly and Report Rejection Reasons

**Files:**
- Modify: `apps/backend/app/services/location_enrichment.py`
- Modify: `apps/backend/app/agents/external_discovery_agent.py`
- Test: `apps/backend/tests/unit/test_geoapify_location.py`
- Test: `apps/backend/tests/unit/test_discovery_pending_status.py`

**Interfaces:**
- Produces: `VerifiedLocation.confidence: float | None`.
- Produces: immutable `LocationResolution(location, rejection_reasons)`.
- Produces: `GeoapifyLocationService.resolve(supplier, constraints) -> LocationResolution`.
- Keeps: `GeoapifyLocationService.enrich(...) -> VerifiedLocation | None` as a compatibility wrapper.
- Produces: `external_discovery_stats["location_rejection_reasons"]`.

- [ ] **Step 1: Add failing Places-contract tests**

```python
def test_geoapify_places_accepts_matching_feature_without_geocoding_rank():
    feature = _feature(city="Munich", name="Hogge Precision")
    feature["properties"].pop("rank")
    client = _Client([{"features": [feature]}])
    service = GeoapifyLocationService(
        geocoding_api_key="",
        places_api_key="places-key",
        client=client,
    )

    resolution = service.resolve(
        {"name": "Hogge Precision"},
        {"location_city": "Munich", "location_country": "Germany"},
    )

    assert resolution.location is not None
    assert resolution.location.source == "geoapify_places"
    assert resolution.location.confidence is None
    assert resolution.rejection_reasons == ()


def test_geoapify_geocoding_still_rejects_missing_rank_confidence():
    feature = _feature(city="Munich", name="Hogge Precision")
    feature["properties"].pop("rank")
    client = _Client([{"features": [feature]}])
    service = GeoapifyLocationService(
        geocoding_api_key="geo-key",
        places_api_key="",
        client=client,
    )

    resolution = service.resolve(
        {"name": "Hogge Precision"},
        {"location_city": "Munich", "location_country": "Germany"},
    )

    assert resolution.location is None
    assert "geocoding_confidence_missing" in resolution.rejection_reasons
```

Add separate tests for Places name mismatch, country conflict, city conflict, and missing coordinates.

- [ ] **Step 2: Add failing external-discovery diagnostic aggregation test**

Configure a fake location resolver to return:

```python
LocationResolution(
    location=None,
    rejection_reasons=(
        "geocoding_company_name_mismatch",
        "places_no_feature",
    ),
)
```

Assert:

```python
assert result["external_discovery_stats"]["location_rejection_reasons"] == {
    "geocoding_company_name_mismatch": 1,
    "places_no_feature": 1,
}
```

- [ ] **Step 3: Run focused tests and confirm RED**

Run:

```bash
cd apps/backend
uv run pytest tests/unit/test_geoapify_location.py tests/unit/test_discovery_pending_status.py -q
```

Expected: `resolve`, nullable confidence, and diagnostic counters do not exist.

- [ ] **Step 4: Add immutable resolution types**

```python
@dataclass(frozen=True)
class VerifiedLocation:
    city: str
    country: str
    latitude: float
    longitude: float
    formatted_address: str | None
    source: str
    confidence: float | None


@dataclass(frozen=True)
class LocationResolution:
    location: VerifiedLocation | None
    rejection_reasons: tuple[str, ...] = ()
```

Change `_confidence` to return `float | None`. Missing or non-numeric values remain rejected by Geocoding, but no fabricated number is returned.

- [ ] **Step 5: Implement source-specific feature validation**

Refactor `_location_from_feature` to return `LocationResolution` and accept
`require_confidence: bool`.

Validation order:

1. expected company name;
2. city;
3. country;
4. coordinates;
5. numeric confidence when `require_confidence=True`;
6. configured threshold when a numeric confidence exists.

Call it with `require_confidence=True` for Geocoding and `False` for Places. Preserve exact reason names prefixed by the path, for example
`geocoding_confidence_below_threshold` and `places_company_name_mismatch`.

Add:

```python
def resolve(
    self,
    supplier: dict,
    constraints: Mapping[str, Any] | None = None,
) -> LocationResolution:
    ...

def enrich(
    self,
    supplier: dict,
    constraints: Mapping[str, Any] | None = None,
) -> VerifiedLocation | None:
    return self.resolve(supplier, constraints).location
```

The resolver must aggregate unique reasons in stable encounter order and must not store them on the service instance.

- [ ] **Step 6: Aggregate bounded diagnostics in the agent**

Use `collections.Counter[str]`. Call `resolve` when available, increment counters for rejected candidates, and preserve compatibility with simple test fakes that expose only `enrich`.

Include sorted counts in `external_discovery_stats` and the audit output summary. Never include raw page content, API keys, or complete external payloads.

- [ ] **Step 7: Run focused tests and confirm GREEN**

Run:

```bash
cd apps/backend
uv run pytest tests/unit/test_geoapify_location.py tests/unit/test_discovery_pending_status.py -q
uv run ruff check app/services/location_enrichment.py app/agents/external_discovery_agent.py tests/unit/test_geoapify_location.py tests/unit/test_discovery_pending_status.py
uv run mypy app/services/location_enrichment.py app/agents/external_discovery_agent.py
```

- [ ] **Step 8: Commit and push immediately**

Run:

```bash
git add apps/backend/app/services/location_enrichment.py \
  apps/backend/app/agents/external_discovery_agent.py \
  apps/backend/tests/unit/test_geoapify_location.py \
  apps/backend/tests/unit/test_discovery_pending_status.py
git commit -m "Explain and validate every supplier location decision"
git push origin production/agentic-suppliermind
git push origin HEAD:main
```

---

### Task 4: Add an Isolated, Idempotent Demo Supplier Floor

**Files:**
- Create: `apps/backend/app/services/demo_seed.py`
- Create: `apps/backend/demo/german_breweries.json`
- Create: `apps/backend/scripts/seed_demo_suppliers.py`
- Create: `apps/backend/tests/unit/test_demo_seed.py`

**Interfaces:**
- Produces: `load_demo_records(path: Path) -> list[dict[str, Any]]`.
- Produces: `stable_demo_supplier_id(seed_key: str) -> uuid.UUID`.
- Produces: `seed_demo_suppliers(db, vector_store, records) -> DemoSeedStats`.
- Uses official product and imprint/contact URLs for every record.

- [ ] **Step 1: Add failing fixture-validation tests**

```python
def test_demo_fixture_is_separate_source_cited_and_approved():
    records = load_demo_records(DEMO_FIXTURE)
    assert 4 <= len(records) <= 6
    for record in records:
        assert record["source"] == "demo_manual"
        assert record["status"] == "approved"
        assert record["source_url"].startswith("https://")
        assert record["source_citations"]["products"]["url"].startswith("https://")
        assert record["source_citations"]["location"]["url"].startswith("https://")
        assert record["country"] == "Germany"
        assert record["latitude"] is not None
        assert record["longitude"] is not None
```

Add tests proving stable IDs and that two seed calls update the same rows while the fake vector store contains one active embedding per stable supplier ID.

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```bash
cd apps/backend
uv run pytest tests/unit/test_demo_seed.py -q
```

Expected: module, fixture, and service are absent.

- [ ] **Step 3: Create the official-source-cited fixture**

Use four to six breweries. Initial verified sources include:

- Paulaner product and imprint:
  `https://www.paulaner.com/our-products/muenchner-hell` and
  `https://www.paulaner.com/es/aviso-legal/imprint`
- Hofbräu Original and imprint:
  `https://www.hofbraeu-muenchen.de/biere-von-hb-muenchen/hofbraeu-original` and
  `https://www.hofbraeu-muenchen.de/en/imprint`
- Giesinger Münchner Hell, Feines Pilschen, and imprint:
  `https://giesinger-braeu.de/products/original-munchner-hell-kopie`,
  `https://giesinger-braeu.de/products/giesinger-feines-pilschen-0-33l-kopie`,
  and `https://giesinger-braeu.de/policies/legal-notice`
- Ayinger Lager Hell, Bairisch Pils, and brewery address:
  `https://www.ayinger.de/cms/files/Medien/Content/Brauerei/Umwelt/Umwelterklaerung_2018.pdf`
  and
  `https://www.ayinger.de/cms/files/Medien/Content/Brauerei/Stellenangebote/Homepage%20Gebietsverkaufsleiter%20Gastronomie.pdf`

Every stored product, address, city, and coordinate must be traceable to the cited official source. Do not store unsupported capacity, lead-time, certification, or wholesale claims.

- [ ] **Step 4: Implement validation and deterministic upsert**

Use a fixed UUID namespace and `uuid.uuid5(namespace, seed_key)`. Validate records before opening a transaction. Only mutate rows with the matching stable ID and `source="demo_manual"`; fail closed if that ID belongs to another source.

For each stable ID:

1. create or update the approved PostgreSQL row;
2. delete its existing vector entry;
3. add exactly one current supplier embedding;
4. store the embedding ID;
5. commit after all rows and embeddings succeed.

Return frozen counts:

```python
@dataclass(frozen=True)
class DemoSeedStats:
    inserted: int
    updated: int
    indexed: int
```

- [ ] **Step 5: Add the explicit command**

`seed_demo_suppliers.py` must initialize the configured vector store, load only
`apps/backend/demo/german_breweries.json`, run the service, print counts, and exit non-zero on validation or persistence failure. It must never import benchmark ingestion or generation modules.

- [ ] **Step 6: Run focused tests and seed the local demo database**

Run:

```bash
cd apps/backend
uv run pytest tests/unit/test_demo_seed.py -q
uv run ruff check app/services/demo_seed.py scripts/seed_demo_suppliers.py tests/unit/test_demo_seed.py
uv run mypy app/services/demo_seed.py scripts/seed_demo_suppliers.py
uv run python scripts/seed_demo_suppliers.py
```

Run the seed command twice. Expected: the second run inserts zero new rows, updates the same records, and leaves one active vector per stable ID.

- [ ] **Step 7: Prove benchmark isolation**

Run:

```bash
git diff --exit-code origin/main -- \
  apps/backend/data/queries_benchmark.json \
  apps/backend/data/suppliers_synthetic.json \
  apps/backend/data/suppliers_synthetic_10k.json \
  apps/backend/data/generate_dataset.py \
  apps/backend/data/thesis_report.json \
  results
cd apps/backend
uv run pytest tests/unit/test_country_scope.py tests/unit/test_paradigm_baselines.py -q
```

- [ ] **Step 8: Commit and push immediately**

Run:

```bash
git add apps/backend/app/services/demo_seed.py \
  apps/backend/demo/german_breweries.json \
  apps/backend/scripts/seed_demo_suppliers.py \
  apps/backend/tests/unit/test_demo_seed.py
git commit -m "Add a dependable source-cited demo supplier floor"
git push origin production/agentic-suppliermind
git push origin HEAD:main
```

---

### Task 5: Add One-Command Release and Live API Verification

**Files:**
- Create: `scripts/verify_release.sh`
- Create: `apps/backend/scripts/verify_live_discovery.py`
- Test: `apps/backend/tests/unit/test_live_verification_script.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `scripts/verify_release.sh [--live]`.
- `--live` consumes a running backend at `SUPPLIERMIND_API_URL`, defaulting to `http://127.0.0.1:8000/api/v1`.
- Live verification submits the original country-only request, observes clarification, answers `Munich`, verifies resume to a terminal status, then verifies a separate `all of Germany` path.

- [ ] **Step 1: Add failing tests for live-event parsing**

Keep network calls outside unit tests. Extract pure helpers in the live script:

```python
def parse_sse_events(lines: Iterable[str]) -> list[tuple[str, dict[str, Any]]]:
    ...

def assert_clarification_question(payload: dict[str, Any], country: str) -> None:
    ...
```

Test multiline event parsing, clarification detection, terminal completion, and clear failure messages.

- [ ] **Step 2: Run tests and confirm RED**

Run:

```bash
cd apps/backend
uv run pytest tests/unit/test_live_verification_script.py -q
```

- [ ] **Step 3: Implement the API-level live verifier**

The script must:

1. obtain a development session through `/auth/dev-login`;
2. submit the country-only query with `search_scope="both"`;
3. consume `/queries/{id}/stream`;
4. require `needs_clarification`;
5. submit `Munich` to `/queries/{id}/clarify`;
6. reconnect to the same stream and require a terminal event;
7. fetch and validate the persisted result and audit trail;
8. repeat with a new query whose clarification answer is `all of Germany`;
9. redact tokens and never print credentials.

- [ ] **Step 4: Implement the root verification command**

`scripts/verify_release.sh` must use `set -euo pipefail`, resolve the repository root without assuming the caller's directory, and run:

```bash
cd apps/backend
uv run pytest
uv run ruff check app tests scripts
uv run mypy app

cd ../frontend
npm test
npm run lint
npm run build
npm run check:bundle

cd ../..
git diff --check
```

Before tests, record the current `thesis-experiments` hash. After tests, assert it is unchanged and assert the protected benchmark paths have no working-tree modifications.

When called with `--live`, additionally run:

```bash
cd apps/backend
uv run python scripts/verify_live_discovery.py
```

- [ ] **Step 5: Document the two commands**

Add concise README instructions:

```text
./scripts/verify_release.sh
./scripts/verify_release.sh --live
```

Explain that `--live` requires the backend and external services to be running.

- [ ] **Step 6: Run focused and full automated verification**

Run:

```bash
cd apps/backend
uv run pytest tests/unit/test_live_verification_script.py -q
cd ../..
chmod +x scripts/verify_release.sh
./scripts/verify_release.sh
```

Expected: one zero exit code for all backend and frontend gates.

- [ ] **Step 7: Commit and push immediately**

Run:

```bash
git add scripts/verify_release.sh \
  apps/backend/scripts/verify_live_discovery.py \
  apps/backend/tests/unit/test_live_verification_script.py \
  README.md
git commit -m "Verify the complete release from one command"
git push origin production/agentic-suppliermind
git push origin HEAD:main
```

---

### Task 6: Run Browser E2E, Generic Query Probes, and Final Cleanup

**Files:**
- Modify only files proven defective by fresh verification evidence.
- Update: `docs/superpowers/plans/2026-07-28-production-discovery-release.md` checkboxes.

**Interfaces:**
- Consumes: running frontend/backend, seeded demo suppliers, live external services.
- Produces: browser evidence for UI clarification/resume and a clean release tree.

- [ ] **Step 1: Start the application and run consolidated live verification**

Run:

```bash
npm run dev
./scripts/verify_release.sh --live
```

Keep the development server in its own terminal session. Do not print environment secrets.

- [ ] **Step 2: Verify the original UI flow in a real browser**

Submit:

```text
i want to buy 1000 (.5l) bottles of helles and Pilsner beer in Germany for the client who is going to organise the summer party.
```

Require:

1. the UI renders the country-scope clarification;
2. answering `Munich` reuses the same query ID;
3. SSE progress resumes;
4. the result reaches a terminal state;
5. approved demo suppliers give the result list an internal-search floor;
6. audit stages render without console or network errors.

Repeat with `all of Germany`.

- [ ] **Step 3: Run generic cross-domain probes**

Use at least:

```text
Find ISO 9001 office furniture manufacturers in Germany.
Find 5000 recyclable food packaging units near Berlin within 30 days.
Find aerospace machining suppliers in Bavaria with AS9100 certification.
Find a textile supplier in France.
```

Verify clarification is requested only for missing hard scope, explicit city/region queries do not re-ask, irrelevant web pages remain excluded, and no beer-specific behavior appears.

- [ ] **Step 4: Run cleanup checks**

Run:

```bash
cd apps/backend
uv run ruff check app tests scripts
uv run mypy app
uv run pytest

cd ../frontend
npm test
npm run lint
npm run build
npm run check:bundle

cd ../..
rg -n "TODO|FIXME|HACK|Task [0-9]+|pony ?tail|temporary|deprecated" \
  apps/backend/app apps/frontend/src scripts
git diff --check
git status --short
```

Inspect every hit. Remove only genuinely stale comments or code, preserve useful rationale, and use existing helpers rather than adding duplicate normalization, location, or seed logic.

- [ ] **Step 5: Run the final one-command verification**

Run:

```bash
./scripts/verify_release.sh
```

Expected: zero exit status with all gates passing.

- [ ] **Step 6: Commit cleanup only if files changed**

Use a human subject describing the actual cleanup, for example:

```bash
git commit -m "Remove stale release comments and duplicate helpers"
```

Push immediately:

```bash
git push origin production/agentic-suppliermind
git push origin HEAD:main
```

- [ ] **Step 7: Confirm remote and thesis state**

Run:

```bash
git fetch origin
git rev-parse HEAD
git rev-parse origin/main
git rev-parse origin/production/agentic-suppliermind
git rev-parse thesis-experiments
git status --short --branch
```

Expected: release, production remote, and `origin/main` match; thesis hash matches the value captured in Task 1; the worktree is clean.
