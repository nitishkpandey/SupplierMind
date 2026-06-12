"""app/schemas/query.py — Pydantic schemas for query API."""

from typing import Literal, Optional
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


# ── Task 3.3 — Multi-turn clarification dialogue ─────────────────────


class ClarificationAnswerRequest(BaseModel):
    """User's reply to a clarification question."""
    answer: str = Field(..., min_length=1, max_length=500)


class ClarificationView(BaseModel):
    """Pending clarification descriptor returned to the frontend."""
    id: str
    question: str
    turn_number: int
    max_turns: int
    created_at: str
