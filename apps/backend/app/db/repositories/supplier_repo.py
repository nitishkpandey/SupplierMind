"""
app/db/repositories/supplier_repo.py — Database operations for Supplier model.

IMPORTANT: This handles STRUCTURED queries (SQL filters).
The Discovery Agent uses this for hard-constraint filtering.
The VectorStore handles SEMANTIC queries (similarity search).
"""

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Supplier
from app.db.repositories.base import BaseRepository
from app.utils.geo import haversine_km
from app.utils.text_normalization import clean_optional_text, clean_text_list


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
        category: str | None = None,
        country: str | None = None,
        required_certifications: list[str] | None = None,
        min_capacity: float | None = None,
        capacity_unit: str | None = None,
        max_lead_time_days: int | None = None,
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
            from sqlalchemy import String, cast
            # Check each certification by casting JSON to text for the LIKE operator
            for cert in required_certifications:
                conditions.append(
                    cast(Supplier.certifications, String).contains(cert)
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
        # This is acceptable for the current 10k-scale corpus; PostGIS
        # ST_DWithin is the production path once this grows materially.
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
            distance = haversine_km(
                center_lat, center_lng,
                supplier.latitude, supplier.longitude  # type: ignore[arg-type]
            )
            if distance <= radius_km:
                nearby.append((supplier, distance))

        # Sort by distance (closest first)
        nearby.sort(key=lambda x: x[1])
        return nearby

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

    # ── SYNC METHODS (used by agent nodes) ───────────────────────────────
    # These are identical in logic to the async methods above,
    # but use a regular Session instead of AsyncSession.

    @staticmethod
    def filter_by_constraints_sync(
        db: "Session",
        category: str | None = None,
        country: str | None = None,
        required_certifications: list[str] | None = None,
        min_capacity: float | None = None,
        capacity_unit: str | None = None,
        max_lead_time_days: int | None = None,
        limit: int = 50,
    ) -> list[Supplier]:
        """Sync version for use inside LangGraph agent nodes."""
        from sqlalchemy import and_

        conditions = [Supplier.is_active == True]  # noqa: E712

        if category:
            conditions.append(Supplier.category == category)
        if country:
            conditions.append(Supplier.country == country)
        if required_certifications:
            from sqlalchemy import String, cast
            for cert in required_certifications:
                conditions.append(cast(Supplier.certifications, String).contains(cert))
        if min_capacity and capacity_unit:
            conditions.append(Supplier.capacity_value >= min_capacity)
            conditions.append(Supplier.capacity_unit == capacity_unit)
        if max_lead_time_days:
            conditions.append(Supplier.lead_time_days <= max_lead_time_days)

        result = db.execute(
            select(Supplier).where(and_(*conditions)).limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    def filter_by_radius_sync(
        db: "Session",
        center_lat: float,
        center_lng: float,
        radius_km: float,
    ) -> list[tuple[Supplier, float]]:
        """Sync geospatial radius filter for use in agent nodes."""
        result = db.execute(
            select(Supplier).where(
                Supplier.is_active == True,  # noqa: E712
                Supplier.latitude.isnot(None),
                Supplier.longitude.isnot(None),
            )
        )
        all_suppliers = list(result.scalars().all())

        nearby = []
        for supplier in all_suppliers:
            distance = haversine_km(
                center_lat, center_lng,
                supplier.latitude,  # type: ignore
                supplier.longitude,  # type: ignore
            )
            if distance <= radius_km:
                nearby.append((supplier, distance))

        nearby.sort(key=lambda x: x[1])
        return nearby

    @staticmethod
    def get_by_ids_sync(db: "Session", ids: list[str]) -> list[Supplier]:
        """Sync bulk fetch by UUID strings."""
        import uuid
        uuid_ids = [uuid.UUID(i) for i in ids if i]
        if not uuid_ids:
            return []
        result = db.execute(
            select(Supplier).where(
                Supplier.id.in_(uuid_ids),
                Supplier.is_active == True,  # noqa: E712
            )
        )
        return list(result.scalars().all())


def supplier_to_dict(supplier: Supplier, *, clean: bool = False) -> dict:
    """Shared Supplier row → plain dict (common keys across agents/baselines).

    clean=True runs text fields through the null-sentinel cleaners
    (agent pipeline); clean=False returns raw column values (baselines).
    Call sites add any extra keys they need via dict.update().
    """
    if clean:
        return {
            "id": str(supplier.id),
            "name": clean_optional_text(supplier.name),
            "country": clean_optional_text(supplier.country),
            "city": clean_optional_text(supplier.city),
            "latitude": supplier.latitude,
            "longitude": supplier.longitude,
            "certifications": clean_text_list(supplier.certifications),
            "capacity_value": supplier.capacity_value,
            "capacity_unit": clean_optional_text(supplier.capacity_unit),
            "lead_time_days": supplier.lead_time_days,
        }
    return {
        "id": str(supplier.id),
        "name": supplier.name,
        "country": supplier.country,
        "city": supplier.city,
        "latitude": supplier.latitude,
        "longitude": supplier.longitude,
        "certifications": list(supplier.certifications or []),
        "capacity_value": supplier.capacity_value,
        "capacity_unit": supplier.capacity_unit,
        "lead_time_days": supplier.lead_time_days,
    }
