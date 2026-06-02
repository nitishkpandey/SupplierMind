"""
app/db/models.py — All database table definitions.

WHY UUID primary keys instead of integers?
Integer IDs are sequential (1, 2, 3...) — this leaks how many records exist.
UUIDs are random — no information leak, works across distributed systems.

WHY JSON columns?
certifications = ["ISO 9001", "ISO 14001"] is stored as JSON.
PostgreSQL handles JSON natively and can query inside it.
Better than creating a separate certifications table for this use case.
"""

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """All models inherit from this base class."""
    pass


# ── Enums ─────────────────────────────────────────────────────────────
class UserRole(str, enum.Enum):
    """
    str + enum.Enum = the value IS the string.
    UserRole.admin == "admin" → True
    This makes JSON serialization trivial.
    """
    admin = "admin"
    procurement_manager = "procurement_manager"
    analyst = "analyst"


class QueryStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class SupplierStatus(str, enum.Enum):
    """
    Tier-based supplier classification.
    approved   = Tier 1: company-wide trusted vendors (admin-curated)
    saved      = Tier 2: personal shortlist (user-saved discoveries)
    discovered = Tier 3: fresh from web, not yet promoted
    rejected   = User marked "not relevant" — excluded from future searches
    """
    approved = "approved"
    saved = "saved"
    discovered = "discovered"
    rejected = "rejected"


# ── Supplier ──────────────────────────────────────────────────────────
class Supplier(Base):
    """
    The central entity. Represents one supplier company.

    Key fields:
    - description: Gets embedded into vectors for semantic search
    - certifications: JSON array ["ISO 9001", "ISO 14001"]
    - latitude/longitude: For Haversine radius calculations
    - embedding_id: The ID of this supplier's vector in Milvus
    - is_active: Soft delete (never hard-delete suppliers)
    """
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    country: Mapped[Optional[str]] = mapped_column(String(100))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    address: Mapped[Optional[str]] = mapped_column(Text)
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    certifications: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    certification_details: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    capacity_value: Mapped[Optional[float]] = mapped_column(Float)
    capacity_unit: Mapped[Optional[str]] = mapped_column(String(50))
    lead_time_days: Mapped[Optional[int]] = mapped_column(Integer)
    website: Mapped[Optional[str]] = mapped_column(String(500))
    contact_email: Mapped[Optional[str]] = mapped_column(String(255))
    embedding_id: Mapped[Optional[str]] = mapped_column(String(255))
    source: Mapped[Optional[str]] = mapped_column(String(50), default="manual")
    # source values: "manual" | "web_discovery" | "imported"

    # ── Production v2: tier classification ─────────────────────────
    status: Mapped[SupplierStatus] = mapped_column(
        SAEnum(SupplierStatus, name="supplierstatus"),
        default=SupplierStatus.approved,
        nullable=False,
        index=True,
    )

    # Provenance URL (where on the web did we find this?)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    # Citation tracking: per-field source URLs for verifiability
    # Example: {"certifications": {"url": "...", "source_phrase": "..."}, ...}
    source_citations: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    # Approval workflow (who promoted this supplier to Tier 1?)
    approved_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # HITL approval rationale (Task 2.4). Captured every time an admin
    # promotes (approves) or removes (rejects) a supplier — the *why*
    # behind the human decision, persisted next to who+when.
    approval_justification: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approval_action: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    approval_decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    query_results: Mapped[list["QueryResult"]] = relationship(
        back_populates="supplier", lazy="select"
    )

    __table_args__ = (
        Index("ix_suppliers_category", "category"),
        Index("ix_suppliers_country", "country"),
        Index("ix_suppliers_is_active", "is_active"),
        Index("ix_suppliers_name", "name"),
    )

    def __repr__(self) -> str:
        return f"<Supplier id={self.id} name={self.name!r}>"



class UserSupplierSave(Base):
    """
    Tier 2 (Saved): Many-to-many between users and suppliers.
    A user can save suppliers to their personal shortlist.
    Saved suppliers remain visible only to the user who saved them.
    """
    __tablename__ = "user_supplier_saves"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_user_supplier_saves_user", "user_id"),
        Index("ix_user_supplier_saves_unique", "user_id", "supplier_id", unique=True),
    )


# ── User ──────────────────────────────────────────────────────────────
class User(Base):
    """
    Supports both OAuth (Google/GitHub) and local email/password.
    oauth_provider + oauth_id identify which service they signed in with.
    hashed_password is only set for local accounts.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="userrole"), default=UserRole.analyst, nullable=False
    )
    oauth_provider: Mapped[Optional[str]] = mapped_column(String(50))
    oauth_id: Mapped[Optional[str]] = mapped_column(String(255))
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    queries: Mapped[list["Query"]] = relationship(back_populates="user", lazy="select")

    __table_args__ = (Index("ix_users_email", "email", unique=True),)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"


# ── Query ─────────────────────────────────────────────────────────────
class Query(Base):
    """
    One procurement discovery request.
    parsed_constraints is the structured JSON output of the Parser Agent.
    Example:
    {
      "category": "metals",
      "location_name": "Bremen",
      "location_lat": 53.0793,
      "location_lng": 8.8017,
      "location_radius_km": 25,
      "certifications": ["ISO 9001"],
      "capacity_min": 5000,
      "capacity_unit": "kg/month"
    }
    """
    __tablename__ = "queries"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    raw_query: Mapped[str] = mapped_column(Text, nullable=False)
    detected_language: Mapped[Optional[str]] = mapped_column(String(10))
    parsed_constraints: Mapped[Optional[dict]] = mapped_column(JSON)
    status: Mapped[QueryStatus] = mapped_column(
        SAEnum(QueryStatus, name="querystatus"),
        default=QueryStatus.pending,
        nullable=False,
    )

    # ── Production v2: routing and evaluation tracking ─────────────
    search_scope: Mapped[str] = mapped_column(
        String(20), default="approved_only", nullable=False
    )
    evaluator_retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    evaluator_verdict: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    execution_time_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="queries")
    results: Mapped[list["QueryResult"]] = relationship(
        back_populates="query", lazy="select", order_by="QueryResult.rank"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        back_populates="query", lazy="select", order_by="AuditLog.timestamp"
    )

    __table_args__ = (
        Index("ix_queries_user_id", "user_id"),
        Index("ix_queries_status", "status"),
        Index("ix_queries_created_at", "created_at"),
    )


# ── QueryResult ───────────────────────────────────────────────────────
class QueryResult(Base):
    """
    One supplier result within one query.
    Stores the rank, scores, compliance check, and AI explanation.

    compliance_matrix example:
    {
      "ISO 9001": "PASS",
      "location_radius": "PASS",
      "capacity": "PARTIAL",
      "lead_time": "PASS"
    }
    """
    __tablename__ = "query_results"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    query_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("queries.id"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    constraint_score: Mapped[float] = mapped_column(Float, default=0.0)
    semantic_score: Mapped[float] = mapped_column(Float, default=0.0)
    proximity_score: Mapped[Optional[float]] = mapped_column(Float)
    completeness_score: Mapped[float] = mapped_column(Float, default=0.0)
    compliance_matrix: Mapped[Optional[dict]] = mapped_column(JSON)
    explanation: Mapped[Optional[str]] = mapped_column(Text)
    distance_km: Mapped[Optional[float]] = mapped_column(Float)

    query: Mapped["Query"] = relationship(back_populates="results")
    supplier: Mapped["Supplier"] = relationship(back_populates="query_results")

    __table_args__ = (
        Index("ix_query_results_query_id", "query_id"),
        Index("ix_query_results_rank", "query_id", "rank"),
    )


# ── AuditLog ──────────────────────────────────────────────────────────
class AuditLog(Base):
    """
    Every agent decision is logged here — the audit trail.
    What did the Parser Agent extract? What did Compliance Agent decide?
    This is the 'explainability' feature of SupplierMind.
    """
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Nullable because human-admin entries (Task 2.4) are not query-scoped.
    # Agent rows still set query_id; human_admin rows leave it NULL.
    query_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("queries.id"), nullable=True
    )
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    input_snapshot: Mapped[Optional[dict]] = mapped_column(JSON)
    output_snapshot: Mapped[Optional[dict]] = mapped_column(JSON)
    reasoning: Mapped[Optional[str]] = mapped_column(Text)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    query: Mapped["Query"] = relationship(back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_logs_query_id", "query_id"),
        Index("ix_audit_logs_agent_name", "agent_name"),
    )


# ── GeocodeCache ──────────────────────────────────────────────────────
class GeocodeCache(Base):
    """
    Caches geocoding results so we don't hit Nominatim repeatedly.
    "Bremen" → (53.0793, 8.8017) stored here after first lookup.
    Nominatim rate limit is 1 req/sec — caching prevents hitting it.
    """
    __tablename__ = "geocode_cache"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    query_string: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_geocode_cache_query_string", "query_string", unique=True),
    )