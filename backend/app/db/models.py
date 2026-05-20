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
    query_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("queries.id"), nullable=False
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