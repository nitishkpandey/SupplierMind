"""drop unused geocode_cache table

The geocode_cache table was created in the initial migration but no code
ever read or wrote it — GeocodingService only uses an in-memory cache plus
the Nominatim API. The GeocodeCache model has been removed from
app/db/models.py; this drops the orphaned table.

Revision ID: d7c30a5e9f12
Revises: 1a43bf2d20fa
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7c30a5e9f12"
down_revision: Union[str, None] = "1a43bf2d20fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_geocode_cache_query_string", table_name="geocode_cache")
    op.drop_table("geocode_cache")


def downgrade() -> None:
    op.create_table(
        "geocode_cache",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("query_string", sa.String(length=500), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column(
            "cached_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_string"),
    )
    op.create_index(
        "ix_geocode_cache_query_string", "geocode_cache", ["query_string"], unique=True
    )
