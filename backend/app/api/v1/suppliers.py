"""app/api/v1/suppliers.py — Supplier read endpoints."""

import uuid
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.models import User
from app.db.repositories.supplier_repo import SupplierRepository
from app.db.session import get_db
from app.schemas.supplier import SupplierResponse, SupplierListResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=SupplierListResponse, summary="List suppliers")
async def list_suppliers(
    offset: int = 0,
    limit: int = 20,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
) -> SupplierListResponse:
    """Get paginated list of active suppliers."""
    repo = SupplierRepository(db)
    suppliers = await repo.get_active(offset=offset, limit=limit)
    total = await repo.count_active()
    return SupplierListResponse(
        items=[SupplierResponse.model_validate(s) for s in suppliers],
        total=total,
        page=(offset // limit) + 1,
        page_size=limit,
    )


@router.get("/{supplier_id}", response_model=SupplierResponse, summary="Get supplier by ID")
async def get_supplier(
    supplier_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
) -> SupplierResponse:
    """Get full supplier details by UUID."""
    try:
        sid = uuid.UUID(supplier_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid supplier ID format")

    repo = SupplierRepository(db)
    supplier = await repo.get_by_id(sid)

    if supplier is None or not supplier.is_active:
        raise HTTPException(status_code=404, detail="Supplier not found")

    return SupplierResponse.model_validate(supplier)
