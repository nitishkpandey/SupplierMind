"""
app/main.py — FastAPI application factory. (Phase 1 update)

Changes from Phase 0:
- Added vector store initialization at startup
- Added Redis cache initialization
- Added auth router
- Replaced print() with proper logging (fixes Windows cp1252 encoding)
"""

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.middleware import RateLimitMiddleware, RequestIDMiddleware

# Configure console logging for backend & agent processes
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize all services at startup, clean up at shutdown."""

    # ── STARTUP ──────────────────────────────────────────────────────
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Environment : %s", settings.APP_ENV)
    logger.info("Vector DB   : %s", settings.effective_vector_db)
    logger.info("Lite Mode   : %s", settings.LITE_MODE)

    # ── Model config guardrails (Audit H) ─────────────────────────────
    # Fail loud at boot rather than silently billing $0 mid-run on a model
    # that is missing from the cost table.
    from app.core.llm import is_pinned_snapshot, model_cost_is_known
    _model = settings.OPENAI_MODEL_NAME
    if not is_pinned_snapshot(_model):
        raise RuntimeError(
            f"OPENAI_MODEL_NAME={_model!r} is a floating alias. Refusing to "
            f"start: the primary model must be a pinned dated snapshot "
            f"(e.g. gpt-4o-mini-2024-07-18) for reproducibility. See "
            f"docs/adr/ADR-001-model-pinning.md."
        )
    if not model_cost_is_known(_model):
        raise RuntimeError(
            f"OPENAI_MODEL_NAME={_model!r} has no cost-table entry (exact or "
            f"prefix) in app/core/llm.py. Refusing to start: an unknown model "
            f"would bill $0 silently and corrupt cost metrics. Add it to "
            f"_COST_PER_MTOK_USD."
        )
    logger.info("LLM model   : %s (pinned snapshot, cost-table OK)", _model)

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
        indexed_count = vector_store.count()
        logger.info("Vector store initialized: %d suppliers indexed", indexed_count)
        _log_supplier_index_health(indexed_count)
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

    # NOTE: Starlette applies middleware in reverse-registration order.
    # RequestID must be outermost (registered last) so the ID is available
    # to all inner middleware and route handlers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # Register routers
    from app.api.v1 import auth, evaluation, health, metrics, queries, suppliers, users

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
    app.include_router(
        evaluation.router,
        prefix="/api/v1/eval",
        tags=["Evaluation"],
    )
    app.include_router(
        suppliers.router,
        prefix="/api/v1/suppliers",
        tags=["Suppliers"],
    )
    app.include_router(
        metrics.router,
        prefix="/api/v1/admin",
        tags=["Admin"],
    )
    app.include_router(
        users.router,
        prefix="/api/v1/users",
        tags=["Users"],
    )

    return app


def _log_supplier_index_health(indexed_count: int) -> None:
    """Warn when Postgres has many active suppliers not present in vector search."""
    try:
        from sqlalchemy import func, select

        from app.db.models import Supplier
        from app.db.session import SyncSessionLocal

        with SyncSessionLocal() as db:
            active_count = db.execute(
                select(func.count())
                .select_from(Supplier)
                .where(Supplier.is_active == True)  # noqa: E712
            ).scalar_one()
    except Exception as e:  # noqa: BLE001 - startup health must not block boot
        logger.warning("Could not compare supplier DB/vector counts: %s", e)
        return

    if active_count and indexed_count < active_count:
        logger.warning(
            "Supplier vector index is incomplete: %d indexed vs %d active in Postgres. "
            "Run `uv run python scripts/bulk_ingest_synthetic.py --skip-pg --resume` "
            "from apps/backend to continue indexing.",
            indexed_count,
            active_count,
        )


app = create_app()
