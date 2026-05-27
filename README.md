# SupplierMind 🧠

> **Multi-Agent LLM-Based Supplier Discovery for Procurement Under Multi-Constraint Requirements**

**Master's Thesis** | Gisma University of Applied Sciences | Mercanis GmbH  
**Author:** Nitish Kumar Pandey | Student ID: GH1039520

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green.svg)](https://fastapi.tiangolo.com)
[![React 18](https://img.shields.io/badge/React-18-61DAFB.svg)](https://reactjs.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-orange.svg)](https://github.com/langchain-ai/langgraph)

---

## What is SupplierMind?

suppliers that did NOT exist in your database before you asked the question.

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
    │  (Tavily, Wikidata, OpenSanctions)   │
    │    │  [auto-ingest new suppliers]    │
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
| LLM | Groq (llama-3.3-70b) | Agent reasoning, JSON extraction |
| Embeddings | Voyage AI (voyage-3-lite) | 512-dim semantic vectors |
| Vector DB | Milvus 2.4 | Semantic similarity search |
| Database | PostgreSQL 16 + PostGIS | Supplier data, queries, audit logs |
| Cache | Redis 7 | LLM response cache, sessions |
| Agents | LangGraph 0.2 | Stateful agent graph with cycles |
| Backend | FastAPI + Python 3.11 | REST API + SSE streaming |
| Frontend | React 18 + TypeScript + Vite | Production UI |
| Styling | Tailwind CSS + shadcn/ui | Component library |
| Maps | Leaflet + OpenStreetMap | Geospatial visualization |
| Auth | OAuth2 (Google/GitHub) + JWT | Stateless authentication |
| i18n | react-i18next | English, German, Hindi |
| Infra | Docker Compose + Kubernetes | Local and production deployment |

---

## Setup

### Prerequisites
- Python 3.11+, Node.js 20+, Docker Desktop, Git
- Free API keys: [Groq](https://console.groq.com), [Voyage AI](https://dash.voyageai.com)

### Quick Start

```bash
# 1. Clone
git clone https://github.com/nitishkpandey/SupplierMind.git
cd SupplierMind

# 2. Configure
cp .env.example .env
# Edit .env with your API keys

# 3. Start infrastructure
docker compose up -d

# 4. Backend setup
cd backend
pip install uv
uv sync
uv run alembic upgrade head
uv run python data/generate_dataset.py
uv run python scripts/ingest_suppliers.py
uv run uvicorn app.main:app --reload --port 8000

# 5. Frontend (separate terminal)
cd frontend
npm install
npm run dev

# 6. Open
# Frontend: http://localhost:5173
# API docs: http://localhost:8000/docs
```

### Run Evaluation

```bash
cd backend
# Baselines only (~5 seconds)
uv run python scripts/run_evaluation.py --baselines-only

# Full evaluation including SupplierMind (~15 minutes)
uv run python scripts/run_evaluation.py
```