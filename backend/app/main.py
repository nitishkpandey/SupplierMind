"""
app/main.py — FastAPI application factory.

This file creates the app. Uvicorn imports it to start the server:
    uvicorn app.main:app --reload
"""
import logging

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1 import health


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Code before yield: runs at server startup
    Code after yield: runs at server shutdown

    In Phase 1 we'll add database/vector DB initialization here.
    """
    # STARTUP
    logger = logging.getLogger(__name__)
    logger.info(f"{settings.APP_NAME} v{settings.APP_VERSION} starting...")
    logger.info(f"  Environment : {settings.APP_ENV}")
    logger.info(f"  Vector DB   : {settings.effective_vector_db}")
    logger.info(f"  Lite Mode   : {settings.LITE_MODE}")
    logger.info(f"  API Docs    : http://localhost:8000/docs")

    yield  # Server handles requests here

    # SHUTDOWN
    logger.info(f"{settings.APP_NAME} shutting down")


def create_app() -> FastAPI:
    """
    Creates and configures the FastAPI application.
    Called once at startup.
    """
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Multi-Agent LLM-Based Supplier Discovery for Procurement "
            "Under Multi-Constraint Requirements — Master's Thesis"
        ),
        # /docs only in development — exposes full API in production (security risk)
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        openapi_url="/openapi.json" if settings.is_development else None,
        lifespan=lifespan,
    )

    # CORS — allows React frontend to call this API
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register route groups
    # prefix="" means health is at /health (not /api/v1/health)
    # Infrastructure tools (K8s, Docker) need a stable health URL
    app.include_router(health.router, tags=["Health"])

    # More routers added in Phase 1 and 2:
    # app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
    # app.include_router(queries.router, prefix="/api/v1/queries", tags=["Queries"])
    # app.include_router(suppliers.router, prefix="/api/v1/suppliers", tags=["Suppliers"])

    return app


# Create the app instance — uvicorn imports this
app = create_app()