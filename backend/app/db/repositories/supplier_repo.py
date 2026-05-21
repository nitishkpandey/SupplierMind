"""
app/db/repositories/supplier_repo.py — Database operations for Supplier model.

IMPORTANT: This handles STRUCTURED queries (SQL filters).
The Discovery Agent uses this for hard-constraint filtering.
The VectorStore handles SEMANTIC queries (similarity search).
"""

import math
import uuid
from typing import Optional

from sqlalchemy import and_, select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Supplier
from app.db.repositories.base import BaseRepository


class SupplierRepository(BaseRepository[Supplier]):

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(Supplier, db)

    async def get_active(self, offset: int = 0, limit: int = 50) -> list[Supplier]:
        """Get active (non-deleted) suppliers."""
        result = await self.db.execute(
            select(Supplier)
            .where(Supplier.is_active == True)  # noqa: E712
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_active(self) -> int:
        """Count active suppliers."""
        result = await self.db.execute(
            select(func.count()).select_from(Supplier).where(Supplier.is_active == True)  # noqa: E712
        )
        return result.scalar_one()

    async def get_by_ids(self, ids: list[uuid.UUID]) -> list[Supplier]:
        """
        Fetch multiple suppliers by ID list.
        Used by Discovery Agent to fetch full records after vector search.
        The vector store returns IDs; this fetches the full data.
        """
        if not ids:
            return []
        result = await self.db.execute(
            select(Supplier).where(Supplier.id.in_(ids), Supplier.is_active == True)  # noqa: E712
        )
        return list(result.scalars().all())

    async def get_by_supplier_ids_str(self, ids: list[str]) -> list[Supplier]:
        """
        Same as get_by_ids but accepts string UUIDs.
        Vector stores return IDs as strings.
        """
        uuid_ids = [uuid.UUID(id_str) for id_str in ids if id_str]
        return await self.get_by_ids(uuid_ids)

    async def filter_by_constraints(
        self,
        category: Optional[str] = None,
        country: Optional[str] = None,
        required_certifications: Optional[list[str]] = None,
        min_capacity: Optional[float] = None,
        capacity_unit: Optional[str] = None,
        max_lead_time_days: Optional[int] = None,
    ) -> list[Supplier]:
        """
        Structured filter search — used by Discovery Agent alongside semantic search.

        This is the SQL-based retrieval strategy. It finds suppliers that
        match hard constraints (category, country, certifications).

        PostgreSQL JSON operators:
        - @> means "contains" for JSON arrays
        - So certifications @> '["ISO 9001"]' means "certifications contains ISO 9001"
        """
        conditions = [Supplier.is_active == True]  # noqa: E712

        if category:
            conditions.append(Supplier.category == category)

        if country:
            conditions.append(Supplier.country == country)

        if required_certifications:
            # Check each certification with JSON contains operator
            for cert in required_certifications:
                conditions.append(
                    Supplier.certifications.contains([cert])  # type: ignore[arg-type]
                )

        if min_capacity and capacity_unit:
            conditions.append(Supplier.capacity_value >= min_capacity)
            conditions.append(Supplier.capacity_unit == capacity_unit)

        if max_lead_time_days:
            conditions.append(Supplier.lead_time_days <= max_lead_time_days)

        result = await self.db.execute(
            select(Supplier).where(and_(*conditions)).limit(50)
        )
        return list(result.scalars().all())

    async def filter_by_radius(
        self,
        center_lat: float,
        center_lng: float,
        radius_km: float,
    ) -> list[tuple[Supplier, float]]:
        """
        Geospatial radius filter using Haversine formula.

        WHY NOT PostGIS ST_DWithin?
        PostGIS is available in our Docker image, but requires installing
        the extension per-database and creating geometry columns.
        For the thesis, the Haversine formula in Python is equivalent and simpler.
        For production, PostGIS ST_DWithin would be more efficient.

        Returns list of (Supplier, distance_km) tuples, sorted by distance.
        """
        # First, get all active suppliers with coordinates
        # Then filter in Python using Haversine
        # This is acceptable for 100-1000 suppliers; PostGIS for millions.
        result = await self.db.execute(
            select(Supplier).where(
                Supplier.is_active == True,  # noqa: E712
                Supplier.latitude.isnot(None),
                Supplier.longitude.isnot(None),
            )
        )
        all_suppliers = list(result.scalars().all())

        # Apply Haversine filter
        nearby = []
        for supplier in all_suppliers:
            distance = self._haversine(
                center_lat, center_lng,
                supplier.latitude, supplier.longitude  # type: ignore[arg-type]
            )
            if distance <= radius_km:
                nearby.append((supplier, distance))

        # Sort by distance (closest first)
        nearby.sort(key=lambda x: x[1])
        return nearby

    @staticmethod
    def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """
        Calculate distance in km between two lat/lng coordinates.

        Formula:
        a = sin²(Δlat/2) + cos(lat1) × cos(lat2) × sin²(Δlng/2)
        distance = 2R × arcsin(√a)   where R = 6371km (Earth radius)
        """
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlng / 2) ** 2
        )
        return R * 2 * math.asin(math.sqrt(a))

    async def create_supplier(self, data: dict) -> Supplier:
        """Create a new supplier record."""
        supplier = Supplier(**data)
        self.db.add(supplier)
        await self.db.flush()
        await self.db.refresh(supplier)
        return supplier

    async def update_embedding_id(
        self, supplier_id: uuid.UUID, embedding_id: str
    ) -> None:
        """After indexing in Milvus, store the embedding reference."""
        from sqlalchemy import update
        await self.db.execute(
            update(Supplier)
            .where(Supplier.id == supplier_id)
            .values(embedding_id=embedding_id)
        )

    async def soft_delete(self, supplier_id: uuid.UUID) -> bool:
        """
        Soft delete — sets is_active=False instead of removing the record.
        WHY: Preserves historical query results that reference this supplier.
        """
        supplier = await self.get_by_id(supplier_id)
        if supplier is None:
            return False
        supplier.is_active = False  # type: ignore[assignment]
        await self.db.flush()
        return True
