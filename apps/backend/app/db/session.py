"""
app/db/session.py — Database sessions for async (API routes) and sync (agents).

WHY TWO SESSIONS?
  - FastAPI routes are async → use AsyncSession + asyncpg driver
  - LangGraph agent nodes are sync → use Session + psycopg2 driver
  - Same ORM models, same repositories — only the driver differs

IMPORTANT: Agents MUST use get_sync_db() or SyncSessionLocal.
           API routes MUST use get_db().
           Never mix them.
"""

from collections.abc import AsyncGenerator, Generator
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# ── Async engine (for FastAPI routes) ────────────────────────────────
async_engine = create_async_engine(
    settings.DATABASE_URL,              # postgresql+asyncpg://...
    echo=settings.is_development,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# ── Sync engine (for LangGraph agent nodes) ───────────────────────────
# Convert async URL to sync URL:
#   postgresql+asyncpg://... → postgresql+psycopg2://...
_sync_url = settings.DATABASE_URL.replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)

sync_engine = create_engine(
    _sync_url,
    echo=False,                  # Don't log every agent SQL query
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SyncSessionLocal = sessionmaker(
    sync_engine,
    class_=Session,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ── FastAPI dependencies ───────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Async DB session for FastAPI routes.
    Usage: db: AsyncSession = Depends(get_db)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_sync_db() -> Generator[Session, None, None]:
    """
    Sync DB session for agent nodes.
    Usage: with get_sync_db() as db: ...
    """
    with SyncSessionLocal() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise