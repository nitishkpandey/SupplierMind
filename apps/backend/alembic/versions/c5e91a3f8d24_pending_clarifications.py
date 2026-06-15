"""pending_clarifications table (task 3.3)

Adds the pending_clarifications table that backs Task 3.3's multi-turn
clarification dialogue. One row per open clarification (resolved_at IS NULL);
the row carries enough state (raw query, partial constraints, ReAct trace,
turn number) for the orchestrator to resume the pipeline once the user
answers.

The CHECK constraint `max_turns` is a hard cap at the database level so the
3-turn ceiling survives even if app code drifts.

Revision ID: c5e91a3f8d24
Revises: b4f7a2e9c1d3
Create Date: 2026-06-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID


revision: str = "c5e91a3f8d24"
down_revision: Union[str, None] = "b4f7a2e9c1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_clarifications",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "query_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("queries.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("raw_query", sa.Text(), nullable=False),
        sa.Column("clarification_question", sa.Text(), nullable=False),
        sa.Column("partial_constraints", sa.JSON(), nullable=False),
        sa.Column(
            "react_trace",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column(
            "turn_number",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_answer", sa.Text(), nullable=True),
        sa.CheckConstraint("turn_number <= 3", name="max_turns"),
    )

    op.create_index(
        "ix_pending_clarifications_query_id",
        "pending_clarifications",
        ["query_id"],
    )
    # Partial index — speeds up the common "fetch the user's one open
    # clarification" lookup without growing as resolved rows accumulate.
    op.create_index(
        "ix_pending_clarifications_user_unresolved",
        "pending_clarifications",
        ["user_id"],
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pending_clarifications_user_unresolved",
        table_name="pending_clarifications",
    )
    op.drop_index(
        "ix_pending_clarifications_query_id",
        table_name="pending_clarifications",
    )
    op.drop_table("pending_clarifications")
