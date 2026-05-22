"""
app/main.py — FastAPI application factory. (Phase 1 update)

Changes from Phase 0:
- Added vector store initialization at startup
- Added Redis cache initialization
- Added auth router
- Replaced print() with proper logging (fixes Windows cp1252 encoding)
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize all services at startup, clean up at shutdown."""

    # ── STARTUP ──────────────────────────────────────────────────────
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Environment : %s", settings.APP_ENV)
    logger.info("Vector DB   : %s", settings.effective_vector_db)
    logger.info("Lite Mode   : %s", settings.LITE_MODE)

    # Initialize cache
    from app.core.cache import InMemoryCache, RedisCache, set_cache_instance
    if settings.LITE_MODE:
        set_cache_instance(InMemoryCache())
    else:
        try:
            import redis.asyncio as aioredis
            redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=False)
            await redis_client.ping()
            set_cache_instance(RedisCache(redis_client))
            logger.info("Redis cache connected")
        except Exception as e:
            logger.warning("Redis unavailable (%s), using in-memory cache", e)
            set_cache_instance(InMemoryCache())

    # Initialize vector store
    from app.core.vector_store import create_vector_store, set_vector_store_instance
    try:
        vector_store = create_vector_store()
        set_vector_store_instance(vector_store)
        logger.info("Vector store initialized: %d suppliers indexed", vector_store.count())
    except Exception as e:
        logger.warning("Vector store unavailable at startup: %s", e)
        logger.warning("Run ingestion after starting: python scripts/ingest_suppliers.py")

    logger.info("API docs available at: http://localhost:8000/docs")

    yield  # Server handles requests

    # ── SHUTDOWN ─────────────────────────────────────────────────────
    logger.info("%s shutting down", settings.APP_NAME)


def create_app() -> FastAPI:
    """Creates and configures the FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Multi-Agent LLM-Based Supplier Discovery — Master's Thesis",
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        openapi_url="/openapi.json" if settings.is_development else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    from app.api.v1 import health
    from app.api.v1 import auth
    from app.api.v1 import queries

    app.include_router(health.router, tags=["Health"])
    app.include_router(
        auth.router,
        prefix="/api/v1/auth",
        tags=["Authentication"],
    )
    app.include_router(
        queries.router,
        prefix="/api/v1/queries",
        tags=["Queries"],
    )

    return app


app = create_app()