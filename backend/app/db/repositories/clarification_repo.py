"""app/db/repositories/clarification_repo.py — pending_clarifications CRUD.

One row per open clarification dialogue. The repo exposes both async and
sync entry points: the API layer uses async (FastAPI handlers), the
orchestrator's `parser_node` uses sync (LangGraph runs in a thread).

Task 3.3 — Component B.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.models import PendingClarification

# Hard cap mirroring the DB CHECK constraint. Kept here so app code can
# raise a clean error before the DB rejects the insert.
MAX_CLARIFICATION_TURNS = 3


class MaxTurnsReached(ValueError):
    """Raised when the orchestrator tries to write a 4th turn for a query."""


class ClarificationAlreadyResolved(ValueError):
    """Raised when an answer is submitted to a row that's already closed."""


# ── Async (API layer) ────────────────────────────────────────────────


class ClarificationRepository:
    """Async repository for the FastAPI handlers."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(
        self, clarification_id: uuid.UUID
    ) -> Optional[PendingClarification]:
        result = await self.db.execute(
            select(PendingClarification).where(
                PendingClarification.id == clarification_id
            )
        )
        return result.scalar_one_or_none()

    async def get_open_for_query(
        self, query_id: uuid.UUID
    ) -> Optional[PendingClarification]:
        """The single open clarification for a query, if any.

        Multiple-turn dialogues mean a query can have many rows over its
        lifetime; only the most recent unresolved one matters.
        """
        result = await self.db.execute(
            select(PendingClarification)
            .where(
                PendingClarification.query_id == query_id,
                PendingClarification.resolved_at.is_(None),
            )
            .order_by(PendingClarification.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def mark_resolved(
        self,
        clarification_id: uuid.UUID,
        user_answer: str,
    ) -> None:
        await self.db.execute(
            update(PendingClarification)
            .where(PendingClarification.id == clarification_id)
            .values(
                resolved_at=datetime.now(timezone.utc),
                user_answer=user_answer,
            )
        )
        await self.db.commit()


# ── Sync (orchestrator / Parser node) ────────────────────────────────


def persist_pending_clarification_sync(
    db: Session,
    *,
    query_id: uuid.UUID,
    user_id: uuid.UUID,
    raw_query: str,
    clarification_question: str,
    partial_constraints: dict[str, Any],
    react_trace: list[dict[str, Any]],
    turn_number: int,
) -> uuid.UUID:
    """Insert one row. Returns the new id. Raises MaxTurnsReached at the
    cap (so callers don't waste a round-trip to the DB to learn it).
    """
    if turn_number > MAX_CLARIFICATION_TURNS:
        raise MaxTurnsReached(
            f"Cannot persist turn {turn_number}: cap is {MAX_CLARIFICATION_TURNS}."
        )
    row = PendingClarification(
        id=uuid.uuid4(),
        query_id=query_id,
        user_id=user_id,
        raw_query=raw_query,
        clarification_question=clarification_question,
        partial_constraints=dict(partial_constraints or {}),
        react_trace=list(react_trace or []),
        turn_number=turn_number,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def get_pending_clarification_sync(
    db: Session, clarification_id: uuid.UUID
) -> Optional[PendingClarification]:
    return db.get(PendingClarification, clarification_id)


def mark_resolved_sync(
    db: Session,
    *,
    clarification_id: uuid.UUID,
    user_answer: str,
) -> None:
    db.execute(
        update(PendingClarification)
        .where(PendingClarification.id == clarification_id)
        .values(
            resolved_at=datetime.now(timezone.utc),
            user_answer=user_answer,
        )
    )
    db.commit()
