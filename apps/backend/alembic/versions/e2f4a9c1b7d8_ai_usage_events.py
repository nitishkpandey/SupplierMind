"""Add privacy-safe AI usage events.

Revision ID: e2f4a9c1b7d8
Revises: d7c30a5e9f12
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from alembic import op

revision: str = "e2f4a9c1b7d8"
down_revision: str | None = "d7c30a5e9f12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_events",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("query_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("user_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("job_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column(
            "source_document_id",
            PGUUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("classification", sa.String(length=20), nullable=False),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_units", sa.Integer(), nullable=False),
        sa.Column("output_units", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=14, scale=8)),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("redaction_applied", sa.Boolean(), nullable=False),
        sa.Column("excerpted", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_units >= 0",
            name="ai_usage_input_units_nonnegative",
        ),
        sa.CheckConstraint(
            "output_units >= 0",
            name="ai_usage_output_units_nonnegative",
        ),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name="ai_usage_latency_nonnegative",
        ),
        sa.CheckConstraint(
            "cost_usd IS NULL OR cost_usd >= 0",
            name="ai_usage_cost_nonnegative",
        ),
        sa.CheckConstraint(
            "classification IN "
            "('public','internal','confidential','restricted')",
            name="ai_usage_classification_valid",
        ),
        sa.ForeignKeyConstraint(["query_id"], ["queries.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_usage_events_created_at",
        "ai_usage_events",
        ["created_at"],
    )
    op.create_index(
        "ix_ai_usage_events_query_id",
        "ai_usage_events",
        ["query_id"],
    )
    op.create_index(
        "ix_ai_usage_events_job_id",
        "ai_usage_events",
        ["job_id"],
    )
    op.create_index(
        "ix_ai_usage_events_provider_model",
        "ai_usage_events",
        ["provider", "model"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_usage_events_provider_model",
        table_name="ai_usage_events",
    )
    op.drop_index(
        "ix_ai_usage_events_job_id",
        table_name="ai_usage_events",
    )
    op.drop_index(
        "ix_ai_usage_events_query_id",
        table_name="ai_usage_events",
    )
    op.drop_index(
        "ix_ai_usage_events_created_at",
        table_name="ai_usage_events",
    )
    op.drop_table("ai_usage_events")
