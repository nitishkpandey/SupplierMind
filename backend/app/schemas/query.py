"""app/schemas/query.py — Pydantic schemas for query API."""

from pydantic import BaseModel, Field


class QueryCreate(BaseModel):
    raw_query: str = Field(..., min_length=10, max_length=1000)


class QueryResponse(BaseModel):
    id: str
    raw_query: str
    status: str
    created_at: str
