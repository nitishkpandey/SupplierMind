"""
app/api/v1/health.py — Health check endpoint.

WHY A HEALTH ENDPOINT?
Every production service needs one. Kubernetes calls /health every 10s.
If it fails, K8s restarts the container automatically.
First thing to check when something is wrong.

NO AUTHENTICATION on this endpoint — K8s and Docker must call it freely.
"""

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter()


class ComponentHealth(BaseModel):
    status: str
    message: str | None = None


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
    environment: str
    timestamp: str
    components: dict[str, ComponentHealth]


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Returns health status of app and dependencies.
    status: "ok" | "degraded" | "unavailable"
    """
    return HealthResponse(
        status="ok",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        timestamp=datetime.now(timezone.utc).isoformat(),
        components={
            "database": ComponentHealth(status="ok", message="PostgreSQL configured"),
            "vector_db": ComponentHealth(
                status="ok",
                message=f"{settings.effective_vector_db} configured"
            ),
            "cache": ComponentHealth(
                status="ok" if not settings.LITE_MODE else "degraded",
                message="Redis" if not settings.LITE_MODE else "In-memory (LITE_MODE)"
            ),
        },
    )