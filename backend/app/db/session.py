"""
app/db/session.py — Database connection pool and session factory.

WHY ASYNC?
FastAPI is async. If database calls were synchronous, the entire server
would FREEZE waiting for each query. Async lets the server handle other
requests while waiting for database responses.

WHY A POOL?
Opening a new database connection for every request is slow (~50ms each).
A pool keeps 10 connections always open and reuses them.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

from sqlalchemy.pool import NullPool

# The engine manages the actual database connections
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.is_development,  # Print SQL queries in development
    poolclass=NullPool,            # Disable pooling to fix multi-loop agentic DB access
)

# Factory that creates new session objects
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Keep objects accessible after commit
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency — provides one database session per request.

    Usage in any FastAPI route:
        async def my_route(db: AsyncSession = Depends(get_db)):
            ...

    The 'async with' ensures the session is always closed,
    even if an exception occurs (no connection leaks).
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise