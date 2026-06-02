"""
app/schemas/supplier.py — Pydantic models for supplier API.
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SupplierResponse(BaseModel):
    """Full supplier data returned by the API."""
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    certifications: Optional[list[str]] = None
    certification_details: Optional[dict] = None
    capacity_value: Optional[float] = None
    capacity_unit: Optional[str] = None
    lead_time_days: Optional[int] = None
    website: Optional[str] = None
    contact_email: Optional[str] = None
    source: Optional[str] = None
    status: str
    source_url: Optional[str] = None
    source_citations: Optional[dict] = None
    is_active: bool
    created_at: datetime
    # Task 2.4 — HITL approval rationale, only set after an admin decision.
    approval_justification: Optional[str] = None
    approval_action: Optional[str] = None
    approval_decided_at: Optional[datetime] = None

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
    description: Optional[str] = None
    category: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    certifications: Optional[list[str]] = None
    capacity_value: Optional[float] = Field(None, ge=0)
    capacity_unit: Optional[str] = None
    lead_time_days: Optional[int] = Field(None, ge=0, le=365)
    website: Optional[str] = None
    contact_email: Optional[str] = None


class SupplierListResponse(BaseModel):
    """Paginated list of suppliers."""
    items: list[SupplierResponse]
    total: int
    page: int
    page_size: int
