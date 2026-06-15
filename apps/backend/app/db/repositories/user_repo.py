"""
app/db/repositories/user_repo.py — All database operations for User model.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserRole
from app.db.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(User, db)

    async def get_by_email(self, email: str) -> User | None:
        """Find user by email address (used during login)."""
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_by_oauth(self, provider: str, oauth_id: str) -> User | None:
        """Find user by OAuth provider + provider user ID."""
        result = await self.db.execute(
            select(User).where(
                User.oauth_provider == provider,
                User.oauth_id == oauth_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_oauth_user(
        self,
        email: str,
        name: str,
        provider: str,
        oauth_id: str,
        role: UserRole = UserRole.procurement_manager,
    ) -> User:
        """
        Create a new user from OAuth login.
        First user to sign up gets a role of procurement_manager.
        The admin sets roles manually via the admin panel.
        """
        user = User(
            email=email,
            name=name,
            oauth_provider=provider,
            oauth_id=oauth_id,
            role=role,
            is_active=True,
        )
        self.db.add(user)
        await self.db.flush()  # Assign ID without committing
        await self.db.refresh(user)
        return user

    async def update_last_login(self, user_id: uuid.UUID) -> None:
        """Update the last_login timestamp for a user."""
        from datetime import datetime, timezone
        from sqlalchemy import update
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(last_login=datetime.now(timezone.utc))
        )
