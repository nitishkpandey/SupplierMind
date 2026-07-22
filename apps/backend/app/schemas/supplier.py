"""
app/schemas/supplier.py — Pydantic models for supplier API.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SupplierResponse(BaseModel):
    """Full supplier data returned by the API."""
    id: uuid.UUID
    name: str
    description: str | None = None
    category: str | None = None
    country: str | None = None
    city: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    certifications: list[str] | None = None
    certification_details: dict | None = None
    capacity_value: float | None = None
    capacity_unit: str | None = None
    lead_time_days: int | None = None
    website: str | None = None
    contact_email: str | None = None
    source: str | None = None
    status: str
    source_url: str | None = None
    source_citations: dict | None = None
    is_active: bool
    created_at: datetime
    # Task 2.4 — HITL approval rationale, only set after an admin decision.
    approval_justification: str | None = None
    approval_action: str | None = None
    approval_decided_at: datetime | None = None

    class Config:
        from_attributes = True


class SupplierApprovalRequest(BaseModel):
    """
    Body for POST /suppliers/{id}/approve and /reject.

    The min_length=20 floor is deliberate: it prevents "ok"/"lgtm" rubber-
    stamps and forces a real one-sentence rationale. max_length=1000 stops
    pasted compliance reports while still allowing detailed reasoning.
    """
    justification: str = Field(..., min_length=20, max_length=1000)


class SupplierCreate(BaseModel):
    """Data required to create a new supplier (admin only)."""
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    category: str | None = None
    country: str | None = None
    city: str | None = None
    address: str | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    certifications: list[str] | None = None
    capacity_value: float | None = Field(None, ge=0)
    capacity_unit: str | None = None
    lead_time_days: int | None = Field(None, ge=0, le=365)
    website: str | None = None
    contact_email: str | None = None


class SupplierListResponse(BaseModel):
    """Paginated list of suppliers."""
    items: list[SupplierResponse]
    total: int
    page: int
    page_size: int
