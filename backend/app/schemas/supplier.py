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
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


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
