"""
app/schemas/auth.py — Pydantic models for authentication API.

Pydantic schemas serve two purposes:
1. Validation: incoming request data is validated automatically
2. Serialization: outgoing response data is formatted consistently
"""

from pydantic import BaseModel


class TokenResponse(BaseModel):
    """Returned to the frontend after successful login."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int     # seconds until access token expires
    user_id: str
    email: str
    name: str
    role: str


class RefreshRequest(BaseModel):
    """Body of the token refresh request."""
    refresh_token: str


class UserResponse(BaseModel):
    """Public user profile — returned by /auth/me."""
    id: str
    email: str
    name: str
    role: str
    is_active: bool

    class Config:
        from_attributes = True  # Allow creating from SQLAlchemy model instances
