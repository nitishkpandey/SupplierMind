# SupplierMind 🧠

> Multi-Agent LLM-Based Supplier Discovery for Procurement Under Multi-Constraint Requirements

**Master's Thesis** | Gisma University of Applied Sciences | CdC3-Mercanis GmbH

## What is SupplierMind?

SupplierMind is an AI-powered, multi-agent supplier discovery system.
Procurement managers type a natural-language query and receive a ranked,
explainable shortlist of suppliers in under 2 minutes.

Example query: *"ISO 9001 certified bronze supplier within 25km of Bremen,
capacity above 5000 kg/month"*

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Groq API (llama-3.3-70b) |
| Embeddings | Voyage AI (voyage-3-lite) |
| Vector DB | Milvus 2.4 |
| Database | PostgreSQL 16 + PostGIS |
| Cache | Redis 7 |
| Agents | LangGraph |
| Backend | FastAPI + Python 3.11 |
| Frontend | React 18 + TypeScript + Tailwind |
| Auth | OAuth2 + JWT |
| Maps | Leaflet + OpenStreetMap |

## Setup

See `Documents/08_PreImplementation_Checklist.md` for full setup guide.