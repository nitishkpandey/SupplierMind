"""
app/db/repositories/base.py — Generic base repository with common CRUD operations.

WHY A BASE REPOSITORY?
Every model needs get_by_id, list_all, delete.
Rather than writing those 3 methods 5 times (once per model),
we write them once in BaseRepository and all other repositories inherit.

DRY principle applied at the database layer.
"""

import uuid
from typing import Any, Generic, Type, TypeVar

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Base

# Generic type variable: ModelType can be any SQLAlchemy model
ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Generic CRUD repository.

    Usage:
        class SupplierRepository(BaseRepository[Supplier]):
            def __init__(self, db: AsyncSession):
                super().__init__(Supplier, db)
    """

    def __init__(self, model: Type[ModelType], db: AsyncSession) -> None:
        self.model = model
        self.db = db

    async def get_by_id(self, id: uuid.UUID) -> ModelType | None:
        """Get one record by primary key. Returns None if not found."""
        result = await self.db.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalar_one_or_none()

    async def list_all(
        self,
        offset: int = 0,
        limit: int = 50,
    ) -> list[ModelType]:
        """Get a paginated list of records."""
        result = await self.db.execute(
            select(self.model).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

    async def count(self) -> int:
        """Count total records in the table."""
        result = await self.db.execute(select(func.count()).select_from(self.model))
        return result.scalar_one()

    async def delete(self, id: uuid.UUID) -> bool:
        """
        Hard delete a record. Returns True if deleted, False if not found.
        NOTE: For suppliers, prefer soft delete (is_active=False).
        Use this only for records that SHOULD be permanently removed.
        """
        record = await self.get_by_id(id)
        if record is None:
            return False
        await self.db.delete(record)
        await self.db.flush()
        return True
