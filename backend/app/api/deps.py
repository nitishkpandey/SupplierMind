"""
app/api/deps.py — FastAPI dependency injection.

These functions are injected into route handlers with Depends().
They handle authentication, authorization, and database sessions.

USAGE in any route:
    from fastapi import Depends
    from app.api.deps import get_current_user, require_admin
    from app.db.models import User

    @router.get("/protected")
    async def protected_route(current_user: User = Depends(get_current_user)):
        return {"user": current_user.email}

    @router.delete("/admin-only")
    async def admin_route(current_user: User = Depends(require_admin)):
        ...
"""

import uuid
import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.models import User, UserRole
from app.db.repositories.user_repo import UserRepository
from app.db.session import get_db

logger = logging.getLogger(__name__)

# HTTPBearer extracts the token from "Authorization: Bearer <token>" header
# auto_error=False means we handle the error ourselves (better error messages)
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Annotated[str | None, Query(description="JWT access token fallback")] = None,
) -> User:
    """
    Dependency: Extract and validate the JWT, return the current user.

    Flow:
    1. Extract Bearer token from Authorization header, or fallback to ?token= query param
    2. Decode and validate JWT signature + expiry
    3. Look up user in database (confirms user still exists and is active)
    4. Return User model instance

    Raises HTTP 401 if:
    - No token provided
    - Token is invalid or expired
    - User no longer exists or is deactivated
    """
    token_str: str | None = None
    # Avoid logging raw credentials/tokens to prevent leakage into logs.
    logger.info("get_current_user: credentials_present=%s, token_present=%s", bool(credentials), bool(token))
    if credentials:
        token_str = credentials.credentials
    elif token:
        token_str = token

    if not token_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Include 'Authorization: Bearer <token>' header or '?token=<token>' query parameter.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(token_str)
    except JWTError as e:
        logger.warning("JWT validation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token. Please login again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str: str | None = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim.",
        )

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token.",
        )

    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or deactivated.",
        )

    return user


# ── Role-based access control (RBAC) ──────────────────────────────────
def require_role(*roles: UserRole):
    """
    Factory function that creates a dependency requiring specific roles.

    Usage:
        @router.post("/admin-only")
        async def admin_route(
            current_user: User = Depends(require_role(UserRole.admin))
        ):
            ...

        @router.post("/managers-and-admins")
        async def manager_route(
            current_user: User = Depends(
                require_role(UserRole.admin, UserRole.procurement_manager)
            )
        ):
            ...
    """
    async def role_checker(
        current_user: Annotated[User, Depends(get_current_user)]
    ) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {[r.value for r in roles]}. "
                       f"Your role: {current_user.role.value}",
            )
        return current_user

    return role_checker


# Pre-built role dependencies for convenience
require_admin = require_role(UserRole.admin)
require_manager = require_role(UserRole.admin, UserRole.procurement_manager)
require_any_role = require_role(UserRole.admin, UserRole.procurement_manager, UserRole.analyst)
