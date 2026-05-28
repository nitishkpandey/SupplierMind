"""
app/api/v1/auth.py — OAuth2 authentication routes.

OAUTH2 FLOW (Google example):
  1. Frontend: user clicks "Sign in with Google"
  2. Frontend calls: GET /api/v1/auth/google/authorize
  3. Backend: redirects to Google's OAuth consent screen
  4. User: approves access
  5. Google: redirects to /api/v1/auth/google/callback?code=XXXX
  6. Backend: exchanges code for user profile
  7. Backend: creates/updates User in database
  8. Backend: issues JWT access token + refresh token
  9. Backend: redirects to frontend with tokens in URL params
  10. Frontend: stores JWT in memory (Zustand store), starts using API

WHY REDIRECT AT THE END (step 9)?
OAuth happens in the browser. The callback URL is hit by the browser.
We can't return JSON to a browser redirect — we send a redirect to
the frontend with tokens as URL params, and the frontend extracts them.
"""

import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from app.db.models import User, UserRole
from app.db.repositories.user_repo import UserRepository
from app.db.session import get_db
from app.schemas.auth import RefreshRequest, TokenResponse, UserResponse

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Dev Login (development only) ───────────────────────────────────────
@router.get("/dev-login", summary="Dev-only login bypass")
async def dev_login(
    email: str = Query(default="dev@suppliermind.local"),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """
    Issues a JWT without OAuth. Only works when APP_ENV=development.
    Redirects to /auth/callback like OAuth, so AuthCallbackPage handles it.
    """
    if not settings.is_development:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev login is only available in development mode.",
        )

    user = await _get_or_create_user(
        db,
        email=email,
        name=email.split("@")[0].replace(".", " ").title(),
        provider="dev",
        oauth_id=f"dev-{email}",
    )

    # Promote to manager role if needed so user can submit queries
    if user.role not in (UserRole.procurement_manager, UserRole.admin):
        from sqlalchemy import update as sa_update
        await db.execute(
            sa_update(User)
            .where(User.id == user.id)
            .values(role=UserRole.procurement_manager)
        )
        await db.commit()
        user.role = UserRole.procurement_manager

    jwt_token = create_access_token(
        subject=str(user.id),
        role=user.role.value,
        email=user.email,
    )
    refresh = create_refresh_token(subject=str(user.id))

    return RedirectResponse(
        url=(
            f"{settings.FRONTEND_URL}/auth/callback"
            f"?access_token={jwt_token}"
            f"&refresh_token={refresh}"
            f"&role={user.role.value}"
        )
    )


# ── Google OAuth ───────────────────────────────────────────────────────
@router.get("/google/authorize", summary="Redirect to Google OAuth consent screen")
async def google_authorize() -> RedirectResponse:
    """
    Step 1: Redirect user to Google's OAuth consent screen.
    The user will see "SupplierMind wants to access your Google account".
    """
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID in .env",
        )

    backend_base = settings.BACKEND_URL.rstrip("/")
    redirect_uri = f"{backend_base}/api/v1/auth/google/callback"
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
    }
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    google_url = f"https://accounts.google.com/o/oauth2/v2/auth?{query_string}"
    return RedirectResponse(url=google_url)


@router.get("/google/callback", summary="Handle Google OAuth callback")
async def google_callback(
    code: str = Query(..., description="Authorization code from Google"),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """
    Step 2: Exchange authorization code for user profile and issue JWT.
    Google redirects here after the user approves access.
    """
    backend_base = settings.BACKEND_URL.rstrip("/")
    redirect_uri = f"{backend_base}/api/v1/auth/google/callback"

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )

        if token_response.status_code != 200:
            logger.error("Google token exchange failed: %s", token_response.text)
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL}/login?error=oauth_failed"
            )

        token_data = token_response.json()
        access_token_google = token_data.get("access_token")

        # Get user profile from Google
        profile_response = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token_google}"},
        )
        profile = profile_response.json()

    google_id = profile.get("sub")
    email = profile.get("email", "")
    name = profile.get("name", email.split("@")[0])

    if not google_id or not email:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=profile_failed")

    # Create or update user in database
    user = await _get_or_create_user(db, email, name, "google", google_id)

    # Issue JWT tokens
    jwt_token = create_access_token(
        subject=str(user.id),
        role=user.role.value,
        email=user.email,
    )
    refresh = create_refresh_token(subject=str(user.id))

    # Redirect to frontend with tokens
    frontend_callback = (
        f"{settings.FRONTEND_URL}/auth/callback"
        f"?access_token={jwt_token}"
        f"&refresh_token={refresh}"
        f"&role={user.role.value}"
    )
    return RedirectResponse(url=frontend_callback)


# ── GitHub OAuth ───────────────────────────────────────────────────────
@router.get("/github/authorize", summary="Redirect to GitHub OAuth consent screen")
async def github_authorize() -> RedirectResponse:
    """Redirect user to GitHub OAuth page."""
    if not settings.GITHUB_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth not configured. Set GITHUB_CLIENT_ID in .env",
        )

    backend_base = settings.BACKEND_URL.rstrip("/")
    redirect_uri = f"{backend_base}/api/v1/auth/github/callback"
    github_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={settings.GITHUB_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=user:email"
    )
    return RedirectResponse(url=github_url)


@router.get("/github/callback", summary="Handle GitHub OAuth callback")
async def github_callback(
    code: str = Query(..., description="Authorization code from GitHub"),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Exchange GitHub code for user profile and issue JWT."""
    backend_base = settings.BACKEND_URL.rstrip("/")
    redirect_uri = f"{backend_base}/api/v1/auth/github/callback"
    async with httpx.AsyncClient() as client:
        # Exchange code for access token
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )

        if token_response.status_code != 200:
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL}/login?error=oauth_failed"
            )

        token_data = token_response.json()
        github_token = token_data.get("access_token")

        # Get user profile
        profile_response = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {github_token}"},
        )
        profile = profile_response.json()

        # GitHub might not return email in profile — fetch from /user/emails
        email = profile.get("email")
        if not email:
            emails_response = await client.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {github_token}"},
            )
            emails = emails_response.json()
            primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
            email = primary["email"] if primary else None

    if not email:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=no_email")

    github_id = str(profile.get("id", ""))
    name = profile.get("name") or profile.get("login", email.split("@")[0])

    user = await _get_or_create_user(db, email, name, "github", github_id)

    jwt_token = create_access_token(
        subject=str(user.id), role=user.role.value, email=user.email
    )
    refresh = create_refresh_token(subject=str(user.id))

    frontend_callback = (
        f"{settings.FRONTEND_URL}/auth/callback"
        f"?access_token={jwt_token}"
        f"&refresh_token={refresh}"
        f"&role={user.role.value}"
    )
    return RedirectResponse(url=frontend_callback)


# ── Refresh + Me ───────────────────────────────────────────────────────
@router.post("/refresh", response_model=TokenResponse, summary="Refresh access token")
async def refresh_access_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a refresh token for a new access token."""
    from jose import JWTError
    import uuid

    try:
        payload = decode_refresh_token(body.refresh_token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )

    user_id = uuid.UUID(payload["sub"])
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated.",
        )

    new_token = create_access_token(
        subject=str(user.id), role=user.role.value, email=user.email
    )
    new_refresh = create_refresh_token(subject=str(user.id))

    return TokenResponse(
        access_token=new_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role.value,
    )


@router.get("/me", response_model=UserResponse, summary="Get current user profile")
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)]
) -> UserResponse:
    """Returns the profile of the currently authenticated user."""
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        name=current_user.name,
        role=current_user.role.value,
        is_active=current_user.is_active,
    )


# ── Helper ─────────────────────────────────────────────────────────────
async def _get_or_create_user(
    db: AsyncSession,
    email: str,
    name: str,
    provider: str,
    oauth_id: str,
) -> User:
    """
    Find existing user or create new one.
    Called by both Google and GitHub callbacks.
    DRY: one function instead of duplicating logic in both callbacks.
    """
    user_repo = UserRepository(db)

    # Check if user exists (by OAuth provider ID first, then email)
    user = await user_repo.get_by_oauth(provider, oauth_id)
    if user is None:
        user = await user_repo.get_by_email(email)

    if user is None:
        # New user — create with default role
        user = await user_repo.create_oauth_user(
            email=email,
            name=name,
            provider=provider,
            oauth_id=oauth_id,
        )
        logger.info("New user created: email=%s provider=%s", email, provider)
    else:
        logger.info("Existing user login: email=%s", email)

    await user_repo.update_last_login(user.id)
    return user
