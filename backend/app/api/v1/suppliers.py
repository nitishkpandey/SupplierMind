"""
app/api/v1/suppliers.py — Supplier management and tier workflows.

PRODUCTION V2: Added workflows for saving to shortlists and approving/rejecting.
NOTE on routing: FastAPI evaluates routes top-down. Static/specific routes
(like `/my-list`) MUST come before parameterized routes (like `/{supplier_id}`).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, update, delete, func

from app.api.deps import get_current_user, require_admin, require_manager
from app.db.models import AuditLog, Supplier, User, SupplierStatus, UserSupplierSave
from app.db.repositories.supplier_repo import SupplierRepository
from app.db.session import get_db
from app.schemas.supplier import (
    SupplierApprovalRequest,
    SupplierCreate,
    SupplierListResponse,
    SupplierResponse,
)

router = APIRouter()


@router.get(
    "/my-list",
    response_model=SupplierListResponse,
    summary="Get user's saved and approved suppliers",
)
async def get_my_list(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """
    Returns Tier 1 (approved) AND Tier 2 (user's saved) suppliers.
    """
    # 1. Base query: approved suppliers OR suppliers saved by this user
    cond = or_(
        Supplier.status == SupplierStatus.approved,
        Supplier.id.in_(
            select(UserSupplierSave.supplier_id)
            .where(UserSupplierSave.user_id == current_user.id)
        )
    )

    query = (
        select(Supplier)
        .where(Supplier.is_active == True)
        .where(cond)
        .order_by(Supplier.name.asc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)
    items = result.scalars().all()

    # 2. Count total
    from sqlalchemy import func
    count_query = select(func.count()).select_from(Supplier).where(Supplier.is_active == True).where(cond)
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    return {
        "items": items,
        "total": total,
        "page": (offset // limit) + 1,
        "page_size": limit,
    }


@router.get(
    "",
    response_model=SupplierListResponse,
    summary="List all suppliers",
)
async def list_suppliers(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    category: str | None = None,
    country: str | None = None,
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(require_manager)] = None,
) -> dict:
    """Admin/Manager view of all active suppliers."""
    repo = SupplierRepository(db)
    
    conds = []
    if category:
        conds.append(Supplier.category == category)
    if country:
        conds.append(Supplier.country == country)
    if status_filter:
        conds.append(Supplier.status == status_filter)

    query = select(Supplier).where(Supplier.is_active == True)
    for c in conds:
        query = query.where(c)
        
    query = query.order_by(Supplier.name.asc()).offset(offset).limit(limit)
    items = (await db.execute(query)).scalars().all()

    count_query = select(func.count()).select_from(Supplier).where(Supplier.is_active == True)
    for c in conds:
        count_query = count_query.where(c)
    total = (await db.execute(count_query)).scalar_one()

    return {
        "items": items,
        "total": total,
        "page": (offset // limit) + 1,
        "page_size": limit,
    }


@router.post(
    "",
    response_model=SupplierResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new supplier manually",
)
async def create_supplier(
    supplier_in: SupplierCreate,
    current_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> Supplier:
    """Manually add a supplier (defaults to approved). Admin only."""
    new_supplier = Supplier(
        id=uuid.uuid4(),
        **supplier_in.model_dump(),
        source="manual",
        status=SupplierStatus.approved,
    )
    db.add(new_supplier)
    await db.commit()
    await db.refresh(new_supplier)
    return new_supplier


@router.get(
    "/{supplier_id}",
    response_model=SupplierResponse,
    summary="Get supplier details",
)
async def get_supplier(
    supplier_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> Supplier:
    """Get a specific supplier by ID."""
    repo = SupplierRepository(db)
    supplier = await repo.get_by_id(supplier_id)
    if not supplier or not supplier.is_active:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return supplier


# ── Tier Workflows ───────────────────────────────────────────────────

@router.post(
    "/{supplier_id}/save",
    summary="Save a supplier to personal shortlist",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def save_supplier(
    supplier_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Adds a supplier to the user's personal shortlist (Tier 2)."""
    # Check if already saved
    existing = await db.execute(
        select(UserSupplierSave).where(
            and_(
                UserSupplierSave.user_id == current_user.id,
                UserSupplierSave.supplier_id == supplier_id,
            )
        )
    )
    if existing.scalar_one_or_none():
        return  # Already saved, idempotent

    # Ensure supplier exists
    supplier = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    if not supplier.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Supplier not found")

    save = UserSupplierSave(
        user_id=current_user.id,
        supplier_id=supplier_id,
    )
    db.add(save)
    await db.commit()


@router.delete(
    "/{supplier_id}/save",
    summary="Remove a supplier from personal shortlist",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unsave_supplier(
    supplier_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Removes a supplier from the user's personal shortlist."""
    await db.execute(
        delete(UserSupplierSave).where(
            and_(
                UserSupplierSave.user_id == current_user.id,
                UserSupplierSave.supplier_id == supplier_id,
            )
        )
    )
    await db.commit()


async def _record_admin_decision(
    db: AsyncSession,
    supplier: Supplier,
    admin: User,
    new_status: SupplierStatus,
    action_label: str,
    justification: str,
) -> None:
    """
    Apply an admin decision (approve or reject) to a supplier and persist
    the rationale alongside it. Writes a parallel audit_logs row with
    agent_name='human_admin' so the same audit query that surfaces agent
    reasoning also surfaces human reasoning — the HITL audit trail lives
    in one table.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    previous_status = supplier.status.value if supplier.status else None

    supplier.status = new_status
    supplier.approved_by_user_id = admin.id
    supplier.approved_at = now if new_status == SupplierStatus.approved else supplier.approved_at
    supplier.approval_justification = justification
    supplier.approval_action = action_label
    supplier.approval_decided_at = now

    db.add(
        AuditLog(
            query_id=None,
            agent_name="human_admin",
            action=f"supplier_{action_label}",
            input_snapshot={
                "supplier_id": str(supplier.id),
                "previous_status": previous_status,
            },
            output_snapshot={
                "new_status": new_status.value,
                "justification": justification,
            },
            reasoning=f"Admin {admin.email} {action_label} supplier: {justification}",
            duration_ms=0,
        )
    )

    await db.commit()


@router.post(
    "/{supplier_id}/approve",
    summary="Promote a supplier to Approved (Tier 1)",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def approve_supplier(
    supplier_id: uuid.UUID,
    payload: SupplierApprovalRequest,
    current_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
):
    """
    Promote a discovered supplier to Approved status (Tier 1).
    Admin only: promotion is an org-wide governance event that affects every
    user's 'approved_only' searches. procurement_managers use Tier 2 (saves)
    for personal shortlists.

    Requires a justification body (min 20 chars). The rationale is persisted
    on the supplier row AND written into audit_logs alongside agent decisions.
    """
    supplier = (
        await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    ).scalar_one_or_none()
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    if supplier.status != SupplierStatus.discovered:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve supplier in '{supplier.status.value}' state; "
                   "only 'discovered' suppliers are eligible for promotion.",
        )

    await _record_admin_decision(
        db,
        supplier=supplier,
        admin=current_user,
        new_status=SupplierStatus.approved,
        action_label="approved",
        justification=payload.justification,
    )


@router.post(
    "/{supplier_id}/reject",
    summary="Mark a supplier as rejected",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reject_supplier(
    supplier_id: uuid.UUID,
    payload: SupplierApprovalRequest,
    current_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
):
    """
    Mark a discovered supplier as rejected. Admin only — same governance
    rationale as approve: rejection removes the supplier from every user's
    discovery results, not just the caller's.

    Requires a justification body (min 20 chars), recorded on the supplier
    row and in audit_logs.
    """
    supplier = (
        await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    ).scalar_one_or_none()
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    if supplier.status not in (SupplierStatus.discovered, SupplierStatus.approved):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot reject supplier in '{supplier.status.value}' state.",
        )

    await _record_admin_decision(
        db,
        supplier=supplier,
        admin=current_user,
        new_status=SupplierStatus.rejected,
        action_label="rejected",
        justification=payload.justification,
    )
