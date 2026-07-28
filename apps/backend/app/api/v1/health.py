"""
app/api/v1/health.py — Health check endpoint.

WHY A HEALTH ENDPOINT?
Every production service needs one. Kubernetes calls /health every 10s.
If it fails, K8s restarts the container automatically.
First thing to check when something is wrong.

NO AUTHENTICATION on this endpoint — K8s and Docker must call it freely.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db

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
async def health_check(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> HealthResponse:
    """
    Returns health status of app and dependencies, actually probed.
    status: "ok" | "degraded" | "unavailable"
    Database down → 503 so K8s readiness fails; vector/cache failures
    degrade but keep the endpoint at 200 (the API itself still serves).
    """
    components: dict[str, ComponentHealth] = {}

    try:
        await db.execute(text("SELECT 1"))
        components["database"] = ComponentHealth(status="ok", message="PostgreSQL reachable")
    except Exception as e:
        await db.rollback()
        components["database"] = ComponentHealth(status="unavailable", message=str(e)[:200])

    try:
        from app.core.vector_store import get_vector_store

        indexed = get_vector_store().count()
        components["vector_db"] = ComponentHealth(
            status="ok",
            message=f"{settings.effective_vector_db}: {indexed} indexed",
        )
    except Exception as e:
        components["vector_db"] = ComponentHealth(status="unavailable", message=str(e)[:200])

    try:
        from app.core.cache import get_cache

        cache = get_cache()
        await cache.set("_health_probe", 1, ttl=10)
        if await cache.get("_health_probe") != 1:
            raise RuntimeError("cache round-trip failed")
        components["cache"] = ComponentHealth(
            status="degraded" if settings.LITE_MODE else "ok",
            message="In-memory (LITE_MODE)" if settings.LITE_MODE else "Redis",
        )
    except Exception as e:
        components["cache"] = ComponentHealth(status="unavailable", message=str(e)[:200])

    # The database is the only hard readiness dependency; other components
    # only degrade. Split /livez vs /readyz if K8s ever needs them apart.
    if components["database"].status != "ok":
        overall = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif any(c.status == "unavailable" for c in components.values()):
        overall = "degraded"
    else:
        overall = "ok"

    return HealthResponse(
        status=overall,
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        timestamp=datetime.now(UTC).isoformat(),
        components=components,
    )
