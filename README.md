# SupplierMind 🧠

> **Multi-Agent LLM-Based Supplier Discovery for Procurement Under Multi-Constraint Requirements**

**Master's Thesis** | Gisma University of Applied Sciences | Mercanis GmbH  
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
 PostgreSQL  Milvus Vector DB   Redis Cache
 (supplier   (semantic search)  (LLM resp.)
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
| Cache | Redis 7 | LLM response cache, sessions |
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
# Load the small SupplierBench-25 demo corpus:
uv run python scripts/ingest_suppliers.py

# Load the full synthetic 10k corpus into the active Postgres database.
# This is fast and idempotent. The dashboard count comes from this database.
uv run python scripts/bulk_ingest_synthetic.py --force-pg --skip-milvus

# Optional: build/rebuild the full semantic Milvus index.
# This calls the embedding provider and can take a long time on free tiers.
uv run python scripts/bulk_ingest_synthetic.py --skip-pg --resume
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
|  |  |  |- evaluation/        SupplierBench-25 harness, metrics, report
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
|  |- supervisor/           Thesis materials for the supervisor
|  '- verification/         Verification record (provider, traces, benchmark lock)
|- results/                 Current benchmark archives + diagnostics
|- scripts/                 reproduce_benchmark.ps1 — repo-level benchmark runner
'- root files               README, ARCHITECTURE, BENCHMARK, CONTRIBUTING, LICENSE, package.json
```

## Thesis

Link to the thesis document: _placeholder — added on submission._

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — the five agents, data flow, three-tier governance, audit log
- [BENCHMARK.md](BENCHMARK.md) — SupplierBench-25, metrics, end-to-end reproduction
- [CONTRIBUTING.md](CONTRIBUTING.md) — code style, tests, commit conventions
- [LICENSE](LICENSE) — MIT
