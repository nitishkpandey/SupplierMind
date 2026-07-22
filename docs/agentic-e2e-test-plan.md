# SupplierMind Agentic E2E Test Plan

Last updated: 2026-07-17

Use this checklist after backend or agent changes. It is intentionally query-
agnostic: the goal is to verify behavior classes, not memorize the exact names
returned for one prompt.

## Preflight

Run these before manual UI testing:

```bash
docker compose -f infra/docker/docker-compose.yml up -d
cd apps/backend
uv run alembic upgrade head
uv run python scripts/bulk_ingest_synthetic.py --force-pg --skip-milvus
uv run python scripts/bulk_ingest_synthetic.py --verify-only
uv run uvicorn app.main:app --reload --port 8000
```

Expected health:

- `/api/v1/suppliers/stats` should show about `10,100` active suppliers in a
  fully seeded local database.
- If Milvus is not fully rebuilt, the dashboard may show `reindex needed`.
  That is acceptable for SQL/web-discovery validation but not for final
  semantic-quality signoff.
- A full semantic rebuild requires explicit approval because it calls Voyage
  for the 10k corpus:

```bash
uv run python scripts/bulk_ingest_synthetic.py --skip-pg --reset-milvus
```

## Acceptance Signals

For every query, inspect both the result list and Agent Audit Trail.

- Vague sourcing requests should pause for clarification before discovery.
- `Approved Suppliers Only` should not run external discovery on the first pass.
- `Discover New Suppliers` should run external discovery and keep relevant
  pending-review suppliers visible in the result list.
- Web suppliers must have verified city/country/coordinates, not `null`.
- Certifications for web suppliers must appear only when backed by extracted
  source text.
- Pricing/support-rating requests must be treated as evidence gaps unless
  verified data exists.
- Result counts should normally reach 5 when enough matching suppliers exist;
  fewer than 5 is acceptable only when constraints are genuinely strict and the
  audit explains the exclusions.

## Query Matrix

| # | Query | Scope To Test | What It Exercises | Expected Behavior |
|---|---|---|---|---|
| 1 | Find metal suppliers in Bremen | both | Web discovery, SQL city filter, pending review visibility | 5 results; Bremen approved suppliers plus relevant pending-review web discoveries when found |
| 2 | Find metal suppliers in Bremen | approved_only | Approved DB retrieval without web | 5 active approved Bremen/Germany metal suppliers |
| 3 | Find AS9100 certified aerospace machining suppliers in Bavaria | both | Certification parsing, region handling, Geoapify region guard | AS9100 compliance shown; Bavaria should not be treated as an exact city |
| 4 | I want to buy 1000 wrench, socket wrench, torque tools and hand tools from reliable suppliers in Germany | both | Product keyword extraction, external supplier discovery, evidence/cert handling | Tool suppliers should outrank generic machinery/metals; web certs only with citations |
| 5 | Find bronze suppliers within 50 km of Bremen that can deliver in less than 25 days | both | Radius search, lead-time filter, strict ranking | Results should satisfy radius/lead-time or clearly explain strict exclusions |
| 6 | Find bronze suppliers within 5 km of Bremen with lead times below 25 days | both | Over-strict constraints and relaxation | May return fewer results; audit should show why |
| 7 | Find electronics suppliers near Munich with prototype and low-volume production capability | both | Location + capability matching | Munich/Germany electronics or prototyping suppliers should rank higher |
| 8 | Find packaging manufacturers with 100,000+ units/month capacity near Berlin | both | Capacity parsing and structured retrieval | Capacity should be checked as supplier capacity, not buyer order quantity |
| 9 | Find IATF 16949 certified automotive stamping suppliers near Stuttgart | approved_only | Automotive cert compliance, city proximity | IATF suppliers near Stuttgart should rank ahead of remote matches |
| 10 | Find suppliers in Germany | approved_only | Agentic clarification | Should ask what product/category is needed before searching |
| 11 | I need a certified supplier with good ratings, low delivery time, and reasonable pricing | both | Clarification + unsupported preference handling | Should ask product/location; should not claim ratings/pricing are verified |
| 12 | Give me a supplier with highest rating of support on products | both | Placeholder product and support-rating guard | Should ask product/location or surface unsupported rating evidence gap |
| 13 | Find office furniture suppliers in Germany that have ISO 9001 certification and can deliver within 30 days | both | Product + cert + lead-time + web evidence | Office furniture candidates; certs require evidence |
| 14 | Find office furniture suppliers in Germany | both | Office category expansion and web discovery | Should avoid unrelated food/electronics unless no stronger candidate exists |
| 15 | Find PCB assembly manufacturers in Sweden with prototype capability | both | Non-Germany country handling | Sweden should constrain country; web results need verified Swedish location |
| 16 | Find pharma packaging suppliers in Germany with ISO 15378 | both | Niche certification taxonomy behavior | Unknown/rare certs should be verified or produce clear evidence gaps |
| 17 | Find food ingredient suppliers near Frankfurt with kosher certification | both | Food category, city, cert compliance | Kosher should be treated as certification/compliance evidence |
| 18 | Find textile suppliers in Poland with OEKO-TEX certification | approved_only | Non-Germany internal corpus and cert match | Poland/OEKO-TEX matches should rank ahead of Germany suppliers |
| 19 | Find logistics providers in Hamburg that can deliver within 7 days | both | Service category and lead time | Must not treat `7 days` as capacity |
| 20 | Find large suppliers in Germany | approved_only | Vague product with size preference | Should clarify product/category instead of returning arbitrary suppliers |
| 21 | Find suppliers for stainless steel fasteners in Düsseldorf with ISO 9001 | both | City normalization with umlaut/ASCII variants | Düsseldorf/Duesseldorf should match consistently |
| 22 | Find CNC machining suppliers within 100 km of Munich with AS9100 | both | Radius plus certification | Radius/proximity should influence rank; AS9100 must pass |
| 23 | Find sustainable packaging suppliers in Berlin with FSC certification | both | Sustainability/cert parsing | FSC must be verified; unsupported sustainability claims need evidence |
| 24 | Same as last time but in Bavaria | approved_only | Per-user semantic memory | Should use previous query memory only for the same user, or clarify if no memory exists |
| 25 | Find suppliers for 5000 aluminum housings per month in Germany | both | Capacity-language distinction | `per month` should become supplier capacity; result units should be coherent |

## Regression Watchlist

- `location_country` must never become a city name such as `Bremen`.
- Exact city SQL matches must not be crowded out by stale semantic hits.
- Pending-review web suppliers must be visible in the originating result list,
  not only on the pending-review page.
- `approved_only` should answer from approved/saved database records unless it
  explicitly expands after no candidates.
- `both` should not ingest suppliers with missing verified location.
- A full Milvus rebuild should make `indexed_suppliers` converge with active
  supplier count; until then, the UI should truthfully show `reindex needed`.
