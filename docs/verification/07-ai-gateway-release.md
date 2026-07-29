# AI gateway release verification — 2026-07-29

## Scope

This record closes the AI data-egress, budget, durable usage, admin metrics, and
dashboard slice described by
`docs/superpowers/plans/2026-07-29-ai-gateway-and-usage-observability.md`.

## Verification evidence

- `./scripts/verify_release.sh`: passed.
  - 30 focused AI policy, gateway, and boundary tests passed.
  - 454 backend tests passed.
  - Ruff and mypy passed.
  - Frontend Node and Vitest suites, ESLint, production build, and bundle-size
    checks passed.
  - Protected benchmark paths and the `thesis-experiments` branch remained
    unchanged.
- Alembic current revision: `e2f4a9c1b7d8 (head)`.
- Gateway denial tests prove unbound and over-budget calls do not invoke the
  provider transport.
- A live PostgreSQL row was inspected with classification, purpose,
  provider/model, input/output units, known cost, latency, success outcome, and
  correlation identifier. The row contained no prompt, response, or document
  content.
- Provider SDK imports were confined to:
  - `apps/backend/app/core/llm.py`
  - `apps/backend/app/core/embeddings.py`
- The admin dashboard was rendered against the local API at desktop width. It
  visibly separated known cost, denials, failures, provider/model operations,
  latency, and purpose/agent usage.

## Dependency advisory disposition

`react-router-dom` is pinned to `7.18.2`. npm reports
[`GHSA-qwww-vcr4-c8h2`](https://github.com/advisories/GHSA-qwww-vcr4-c8h2)
for its `react-router` dependency. The reviewed advisory states that it affects
only applications using unstable React Server Component APIs. SupplierMind is
a Vite client-only SPA using `BrowserRouter`; it has no React Router RSC,
framework/server mode, loaders, or actions, so the vulnerable execution path is
not present.

The advisory identifies `8.3.0` as patched, but that release was not available
from the npm registry on 2026-07-29. Upgrade and remove this exception as soon as
`react-router-dom@8.3.0` is published. Do not downgrade to `7.11.0`: that version
reintroduces multiple client-side redirect and XSS advisories that are relevant
to a browser SPA.
