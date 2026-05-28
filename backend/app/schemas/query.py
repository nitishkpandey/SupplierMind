"""app/schemas/query.py — Pydantic schemas for query API."""

from typing import Literal
from pydantic import BaseModel, Field


class QueryCreate(BaseModel):
    raw_query: str = Field(
        ..., min_length=10, max_length=1000, description="The natural language query"
    )
    search_scope: Literal["approved_only", "both"] = Field(
        default="approved_only",
        description="Whether to search only approved suppliers or discover new ones",
    )


class QueryResponse(BaseModel):
    id: str
    raw_query: str
    status: str
    created_at: str
