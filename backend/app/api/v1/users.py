"""app/api/v1/users.py — User-scoped endpoints (Task 3.2).

Currently exposes one endpoint:

    DELETE /api/v1/users/me/memory   — GDPR right-to-be-forgotten

The caller authenticates as themselves; the endpoint removes every row from
the `query_memory` Milvus collection that bears their `user_id`. No
cross-user delete; admins use the same endpoint logged in as themselves.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import get_current_user
from app.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


@router.delete(
    "/me/memory",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete all of the caller's query memory (GDPR right-to-be-forgotten)",
)
async def delete_my_memory(
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Erase every semantic-memory row owned by the current user.

    Returns 204 on success (including the "no rows to delete" case — the
    GDPR contract is met either way). Returns 503 if the memory backend
    is unreachable, so the client can retry later.
    """
    from app.services.query_memory import get_memory_service

    try:
        deleted = get_memory_service().delete_all_for_user(str(current_user.id))
    except Exception as e:  # noqa: BLE001 — surface memory-backend errors as 503
        logger.error("[users.delete_my_memory] memory backend error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory backend temporarily unavailable; please retry.",
        ) from e

    logger.info(
        "[users.delete_my_memory] user=%s deleted=%d rows",
        current_user.id,
        deleted,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
