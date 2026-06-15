"""hitl approval justification (task 2.4)

Adds:
- suppliers.approval_justification (text) — the admin's typed rationale
- suppliers.approval_action          (string) — 'approved' or 'rejected'
- suppliers.approval_decided_at      (timestamp) — when the decision landed

Also makes audit_logs.query_id nullable so human-decision rows can be
written into the same audit_logs table with a NULL query_id (they are
not query-scoped). agent_name='human_admin' distinguishes them from
agent-generated entries.

Revision ID: b4f7a2e9c1d3
Revises: 8fb55de4fa16
Create Date: 2026-06-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4f7a2e9c1d3"
down_revision: Union[str, None] = "8fb55de4fa16"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "suppliers",
        sa.Column("approval_justification", sa.Text(), nullable=True),
    )
    op.add_column(
        "suppliers",
        sa.Column("approval_action", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "suppliers",
        sa.Column(
            "approval_decided_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.alter_column(
        "audit_logs",
        "query_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    # Human-admin rows have NULL query_id; drop them so the NOT NULL
    # constraint can be reinstated cleanly.
    op.execute("DELETE FROM audit_logs WHERE query_id IS NULL")
    op.alter_column(
        "audit_logs",
        "query_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.drop_column("suppliers", "approval_decided_at")
    op.drop_column("suppliers", "approval_action")
    op.drop_column("suppliers", "approval_justification")
