"""app/db/repositories/query_repo.py — Query CRUD operations."""

import uuid
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Query
from app.db.repositories.base import BaseRepository


class QueryRepository(BaseRepository[Query]):

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(Query, db)

    async def get_with_results(self, query_id: uuid.UUID) -> Query | None:
        """Fetch query with all results eagerly loaded."""
        result = await self.db.execute(
            select(Query)
            .options(selectinload(Query.results))
            .where(Query.id == query_id)
        )
        return result.scalar_one_or_none()

    async def get_user_queries(
        self, user_id: uuid.UUID, offset: int = 0, limit: int = 20
    ) -> list[Query]:
        """Get paginated query history for a user."""
        result = await self.db.execute(
            select(Query)
            .where(Query.user_id == user_id)
            .order_by(Query.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())
