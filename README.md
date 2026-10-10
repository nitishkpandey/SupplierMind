# SupplierMind 🧠

> **Multi-Agent LLM-Based Supplier Discovery for Procurement Under Multi-Constraint Requirements**

**Master's Thesis** | Gisma University of Applied Sciences | Mercanis (Cdc3 GmbH)

**Author:** Nitish Kumar Pandey | Student ID: GH1039520

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green.svg)](https://fastapi.tiangolo.com)
[![React 19](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-orange.svg)](https://github.com/langchain-ai/langgraph)

---

## What is SupplierMind?

SupplierMind is an AI-assisted supplier discovery system for procurement teams
that need auditable results under constraints such as certifications, capacity,
lead time, and geography. It searches approved suppliers first, can discover new
web suppliers when requested, and holds those web suppliers for human approval
without hiding them from the originating result list.

**Example query:**
> *"ISO 9001 certified bronze supplier within 25km of Bremen, capacity above 5000 kg/month, lead time under 21 days"*

---

## Architecture

```
React Frontend (TypeScript + Tailwind)
         │
    FastAPI Backend
         │
    ┌────┴─────────────────────────────────┐
    │         LangGraph Pipeline           │
    │  Parser                              │
    │    │                                 │
    │  External Discovery                  │
    │  (Tavily, Geoapify, OpenSanctions)   │
    │    │  [pending-review suppliers]     │
    │  Internal Discovery                  │
    │  (Milvus + PostgreSQL)               │
    │    │                                 │
    │  Compliance (ReAct) → Ranking        │
    └────┬─────────────────────────────────┘
         │
    ┌────┼──────────────────────────┐
    │    │                          │
 PostgreSQL  Milvus Vector DB   Redis-compatible cache
 (supplier   (semantic search)  (runtime support)
  data)
```

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| LLM | OpenAI (gpt-4o-mini-2024-07-18, pinned) | Agent reasoning, JSON extraction |
| Embeddings | Voyage AI (voyage-3-lite) | 512-dim semantic vectors |
| Vector DB | Milvus 2.4 | Semantic similarity search |
| Database | PostgreSQL 16 + PostGIS | Supplier data, queries, audit logs |
| Location | Geoapify Geocoding + Places | Mandatory city/country validation for web suppliers |
| Cache | Redis 7 with in-memory fallback | Shared async cache abstraction and runtime support |
| Agents | LangGraph 0.2 | Stateful agent graph with cycles |
| Backend | FastAPI + Python 3.11 | REST API + SSE streaming |
| Frontend | React 19 + TypeScript + Vite | Production UI |
| Styling | Tailwind CSS + shadcn/ui | Component library |
| Maps | Leaflet + OpenStreetMap | Geospatial visualization |
| Auth | OAuth2 (Google/GitHub) + JWT | Stateless authentication |
| i18n | react-i18next | English and German UI; backend parser accepts multilingual input |
| Infra | Docker Compose + Kubernetes | Local and production deployment |

---

## Setup

### Prerequisites
- Python 3.11+, Node.js 20+, Docker Desktop, Git
- API keys: OpenAI, Voyage AI, Tavily, Geoapify Geocoding, Geoapify Places, and OpenSanctions as configured in `.env.example`

### AI policy configuration

All model and embedding calls pass through a policy and budget gateway. These
variables are required in every environment; the values shown are the safe
defaults in `.env.example`:

| Variable | Default | Purpose |
|---|---:|---|
| `AI_EXTERNAL_ALLOWED_CLASSIFICATIONS` | `public,internal` | Data classes that OpenAI and Voyage may receive |
| `AI_MAX_CALL_TOKENS` | `32000` | Maximum estimated units for one text or embedding call |
| `AI_MAX_CALL_COST_USD` | `0.10` | Maximum estimated cost for one text call |
| `AI_MAX_QUERY_COST_USD` | `0.50` | Shared known-cost ceiling for a query, including resumed turns |

Unbound calls are classified `restricted` and denied. Confidential processing
must not be added to the allow list without documented Mercanis Security and
Legal approval. See
[ADR-003](docs/adr/ADR-003-ai-data-egress-and-usage.md).

### Quick Start

```bash
# 1. Clone
git clone https://github.com/nitishkpandey/SupplierMind.git
cd SupplierMind

# 2. Configure
cp .env.example .env
# Edit .env with your API keys

# 3. Start infrastructure
docker compose -f infra/docker/docker-compose.yml up -d

# 4. Backend setup
cd apps/backend
pip install uv
uv sync
uv run alembic upgrade head
# Load the small local demonstration corpus. This is not the published thesis benchmark:
uv run python scripts/ingest_suppliers.py

# Load the full synthetic 10k corpus into the active Postgres database.
# This is fast and idempotent. The dashboard count comes from this database.
uv run python scripts/bulk_ingest_synthetic.py --force-pg --skip-milvus

# Optional: build/rebuild the full semantic Milvus index.
# This calls the embedding provider and can take a long time on free tiers.
uv run python scripts/bulk_ingest_synthetic.py --skip-pg --resume
# If the checkpoint says complete but Milvus has fewer entities than Postgres,
# rebuild the supplier collection from scratch:
uv run python scripts/bulk_ingest_synthetic.py --skip-pg --reset-milvus
uv run uvicorn app.main:app --reload --port 8000

# 5. Frontend (separate terminal)
cd apps/frontend
npm install
npm run dev

# 6. Open
# Frontend: http://localhost:5173
# API docs: http://localhost:8000/docs
```

### Run Evaluation

The application evaluator below is intended for local product experiments. Its generated files under `apps/backend/data/` are runtime outputs and are not the evidence package used for the published thesis results.

```bash
cd apps/backend
# Baselines only (~5 seconds)
uv run python scripts/run_evaluation.py --baselines-only

# Full evaluation including SupplierMind (~15 minutes)
uv run python scripts/run_evaluation.py
```
```bash
# Three-paradigm run (P1 single-prompt + P2 RAG + P3 SupplierMind)
uv run python scripts/run_evaluation.py --paradigms
```

---

## Release Verification

Run every deterministic backend and frontend quality gate from the repository
root:

```bash
./scripts/verify_release.sh
```

With the backend and its external services running, include the live
country-scope clarification, resume, supplier-result, and audit-trail checks:

```bash
./scripts/verify_release.sh --live
```

The live check uses the development login endpoint and does not print tokens or
credentials.

### AI provider and usage operations

An admin can open `/admin/metrics` to inspect provider/model call counts,
latency, known cost, unknown-cost calls, policy or budget denials, failures, and
the highest-cost query links. The source of truth is PostgreSQL
`ai_usage_events`; prompts, responses, document bodies, and credentials are not
stored in that table.

Run the credentialed provider smoke check without printing the API key or the
model response:

```bash
cd apps/backend
uv run python -c "from scripts.provider_integration_check import check_provider; check_provider()"
```

The check requires the current Alembic schema and writes one
`public/provider.smoke_check` usage event. Keep credentials in `.env` or the
deployment secret store; never pass them on the command line.

For an incident, inspect the content-free rows and application logs using the
event's `correlation_id`:

```sql
SELECT created_at, correlation_id, purpose, classification, operation,
       provider, model, input_units, output_units, cost_usd, latency_ms,
       outcome, error_code
FROM ai_usage_events
WHERE outcome <> 'success'
ORDER BY created_at DESC
LIMIT 100;
```

- `classification_not_allowed`: confirm the call has the intended purpose and
  classification. Do not broaden the allow list to bypass a missing or wrong
  context; confidential external processing requires Security and Legal
  approval.
- `budget_exceeded`: inspect the call estimate and the query's accumulated known
  spend. A resumed query is seeded from persisted spend, so retrying or
  answering a clarification does not reset its budget. Raise a configured limit
  only after validating the workload and cost impact.
- `AI usage persistence failed`: treat the provider result as unaccounted
  usage. Check database connectivity, run `uv run alembic current` (expected
  head: `e2f4a9c1b7d8`), and restore writes before relying on dashboard totals.
  The error log contains only provider, operation, outcome, correlation ID, and
  exception type.

---

## The Three Paradigms

The thesis benchmarks three ways of answering the same procurement query:

| Paradigm | Method | Code |
|---|---|---|
| **P1** | Single-prompt LLM, parametric knowledge only — no corpus, no tools | `apps/backend/experiments/paradigm1_singleprompt.py` |
| **P2** | Minimal RAG: Voyage + Milvus top-10 retrieval, one prompt, pick 5 | `apps/backend/experiments/paradigm2_rag.py` |
| **P3** | SupplierMind: five-agent LangGraph system with ReAct tool use, semantic memory, multi-turn clarification, compliance gating and auditable ranking | `apps/backend/app/` |

Design decisions and the shared output contract are documented in
`apps/backend/experiments/README.md`. Architecture detail per paradigm:
[ARCHITECTURE.md](ARCHITECTURE.md). Benchmark protocol and reproduction:
[BENCHMARK.md](BENCHMARK.md).

## Production vs Thesis Data Modes

SupplierMind is maintained for two related but separate goals:

| Mode | Purpose | Supplier corpus |
|---|---|---|
| Product application | Active product UX and company-ready discovery workflow | Active PostgreSQL suppliers, including synthetic scale data and eligible reviewed discoveries |
| Local evaluator | Development checks for current application behavior | Curated local demonstration corpus |
| Published thesis | Offline reproduction of the reported P1, P2, and P3 comparison | Frozen 10,000-supplier synthetic corpus and SupplierBench-24 archives under `thesis/` |

The published thesis package is deliberately isolated from the current application evaluator. Running the product evaluator cannot overwrite or silently change the archived thesis observations.

## Repository Map

```
SupplierMind/
|- apps/
|  |- backend/              FastAPI app (P3 five-agent system), P1/P2 experiments, data, scripts, tests
|  |  |- app/                  FastAPI application (P3: the five-agent system)
|  |  |  |- agents/            Parser (ReAct), Discovery, Compliance, Ranking, Evaluator
|  |  |  |- agents/tools/      Tool registry + the 5 Parser tools
|  |  |  |- api/v1/            REST + SSE endpoints (queries, clarifications, admin)
|  |  |  |- core/              LLM providers, embeddings, vector store, rate limiter
|  |  |  |- db/                SQLAlchemy models, repositories, Alembic migrations
|  |  |  |- evaluation/        Local evaluation harness, metrics, report
|  |  |  '- services/          Geoapify location enrichment, ingestion, query memory
|  |  |- experiments/          P1 + P2 baseline paradigms
|  |  |- data/                 Synthetic corpus generators (fixed seed 42) + benchmark queries
|  |  |- scripts/              Drivers: evaluation, smoke tests, demos, diagnostics
|  |  '- tests/unit/           173+ deterministic unit tests (no live LLM needed)
|  '- frontend/             React + TypeScript + Tailwind UI
|- infra/
|  |- docker/               docker-compose.yml (+ prod overlay) and nginx.conf
|  '- k8s/                  Kubernetes manifests (namespace, deployments, secrets example)
|- docs/
|  |- adr/                  Architecture decision records
|  |- research/             Evaluation protocol
|  '- verification/         Production release verification
|- thesis/                  Published offline reproduction package
|- scripts/                 Release and local evaluation helpers
'- root files               README, ARCHITECTURE, BENCHMARK, CONTRIBUTING, LICENSE, package.json
```

## Thesis

The public evidence package is documented in [thesis/README.md](thesis/README.md). It contains SupplierBench-24, sanitized archived observations, provenance, deterministic analysis scripts, generated figures, and integrity tests.

Reproduce and verify the thesis results without API credentials or running services:

```bash
npm run thesis:reproduce
```

This reproduces the analysis from archived observations. It is intentionally different from a paid live rerun of stochastic model calls.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — the five agents, data flow, three-tier governance, audit log
- [BENCHMARK.md](BENCHMARK.md) — SupplierBench-24 protocol, correction, metrics, and reproduction
- [thesis/README.md](thesis/README.md) — public thesis evidence and provenance
- [docs/agentic-e2e-test-plan.md](docs/agentic-e2e-test-plan.md) — 25-query acceptance matrix for agentic behavior, retrieval, web discovery, compliance, and known index health checks
- [CONTRIBUTING.md](CONTRIBUTING.md) — code style, tests, commit conventions
- [LICENSE](LICENSE) — MIT
