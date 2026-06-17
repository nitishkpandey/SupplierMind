"""add pending_review supplier status

Adds a new value 'pending_review' to the supplierstatus enum so that
web-discovered suppliers can enter a human-in-the-loop holding state
(awaiting admin approval) instead of bypassing the approval workflow.

Postgres version note:
The target server is PostgreSQL 16 (>= 12). Since PG 12, `ALTER TYPE ...
ADD VALUE` is allowed inside a transaction block, so no autocommit/isolation
handling is required here — Alembic's default transactional DDL is fine. The
only PG 12+ caveat (the newly added value cannot be *used* in the same
transaction that adds it) does not apply, because this migration only adds
the label and does not insert/compare rows using it. We therefore took the
plain transactional path; no `op.get_bind().execution_options(...)` autocommit
shim was needed.

`ADD VALUE IF NOT EXISTS` makes the upgrade idempotent.

Revision ID: 1a43bf2d20fa
Revises: c5e91a3f8d24
Create Date: 2026-06-17 13:44:07.991798

"""
from typing import Sequence, Union
from alembic import op


revision: str = '1a43bf2d20fa'
down_revision: Union[str, None] = 'c5e91a3f8d24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE supplierstatus ADD VALUE IF NOT EXISTS 'pending_review'")


def downgrade() -> None:
    # No-op: PostgreSQL has no native, transactionally-safe way to drop a
    # value from an enum type. Removing 'pending_review' would require
    # recreating the type and rewriting every dependent column, which is not
    # cleanly reversible. Leaving the unused label in place is harmless.
    pass
