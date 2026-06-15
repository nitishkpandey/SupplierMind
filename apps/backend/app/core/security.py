"""
app/core/security.py — JWT token creation, validation, and password hashing.

NEVER import this from agents.
ONLY import this from:
  - app/api/v1/auth.py (creating tokens after login)
  - app/api/deps.py (validating tokens on each request)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

logger = logging.getLogger(__name__)

# Algorithm for JWT signing
ALGORITHM = "HS256"

# bcrypt context for hashing local passwords
# Why bcrypt? It's deliberately slow, making brute-force attacks impractical.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Token Creation ─────────────────────────────────────────────────────
def create_access_token(
    subject: str,
    role: str,
    email: str,
    extra_data: dict[str, Any] | None = None,
) -> str:
    """
    Create a JWT access token.

    Args:
        subject: The user's UUID (stored in 'sub' claim — standard JWT field)
        role: User role (admin, procurement_manager, analyst)
        email: User email address
        extra_data: Any additional claims to include

    Returns:
        Signed JWT string

    The token contains:
    {
      "sub": "user-uuid",
      "role": "procurement_manager",
      "email": "user@company.com",
      "type": "access",
      "iat": 1716000000,   <- issued at
      "exp": 1716086400    <- expires at (24h later)
    }
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "email": email,
        "type": "access",
        "iat": now,
        "exp": expire,
    }
    if extra_data:
        payload.update(extra_data)

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(subject: str) -> str:
    """
    Create a refresh token.
    Contains only the user ID — minimal data for security.
    Stored in Redis server-side (can be invalidated on logout).
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    payload = {
        "sub": subject,
        "type": "refresh",
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


# ── Token Validation ───────────────────────────────────────────────────
def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT token.

    Validates:
    1. Signature (was this token signed with our SECRET_KEY?)
    2. Expiry (has the token expired?)
    3. Algorithm (is it using HS256?)

    Args:
        token: The JWT string from the Authorization header

    Returns:
        Decoded payload dict

    Raises:
        JWTError: If token is invalid, expired, or tampered with
    """
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[ALGORITHM],
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode an access token and verify it's the right type.

    Raises:
        JWTError: If invalid, expired, or not an access token
    """
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise JWTError("Token is not an access token")
        return payload
    except JWTError:
        raise


def decode_refresh_token(token: str) -> dict[str, Any]:
    """Decode a refresh token and verify it's the right type."""
    try:
        payload = decode_token(token)
        if payload.get("type") != "refresh":
            raise JWTError("Token is not a refresh token")
        return payload
    except JWTError:
        raise


# ── Password Hashing ───────────────────────────────────────────────────
def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)
