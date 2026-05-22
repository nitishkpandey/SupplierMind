"""
app/api/v1/queries.py — Query submission and results endpoints with SSE streaming.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import run_pipeline
from app.api.deps import get_current_user, require_manager
from app.db.models import Query, QueryResult, AuditLog, QueryStatus, User
from app.db.repositories.query_repo import QueryRepository
from app.db.session import get_db
from app.schemas.query import QueryCreate, QueryResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory store for SSE progress updates {query_id: list of events}
# In production this would be Redis pub/sub
_sse_events: dict[str, list[dict]] = {}


@router.post(
    "",
    response_model=QueryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a procurement query",
)
async def submit_query(
    body: QueryCreate,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(require_manager)],
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    """
    Submit a natural-language procurement query.
    Returns immediately with query_id.
    Poll GET /{query_id} or stream GET /{query_id}/stream for results.
    """
    # Validate query length
    if len(body.raw_query.strip()) < 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query too short. Please provide more details.",
        )
    if len(body.raw_query) > 1000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query too long. Maximum 1000 characters.",
        )

    # Check for prompt injection
    injection_patterns = [
        "ignore previous instructions",
        "ignore all instructions",
        "you are now",
        "act as",
        "disregard",
        "new persona",
    ]
    query_lower = body.raw_query.lower()
    if any(p in query_lower for p in injection_patterns):
        logger.warning(
            "Prompt injection detected from user=%s: %r",
            current_user.id,
            body.raw_query[:100],
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query contains disallowed patterns.",
        )

    # Create Query record in database
    query = Query(
        id=uuid.uuid4(),
        user_id=current_user.id,
        raw_query=body.raw_query.strip(),
        status=QueryStatus.pending,
    )
    db.add(query)
    await db.flush()
    await db.refresh(query)
    query_id = str(query.id)

    # Initialise SSE event buffer for this query
    _sse_events[query_id] = []

    # Run pipeline in background (non-blocking)
    background_tasks.add_task(
        _run_pipeline_background,
        query_id=query_id,
        raw_query=body.raw_query.strip(),
        user_id=str(current_user.id),
    )

    return QueryResponse(
        id=query_id,
        raw_query=body.raw_query,
        status="pending",
        created_at=query.created_at.isoformat(),
    )


@router.get(
    "/{query_id}/stream",
    summary="Stream real-time agent progress via SSE",
)
async def stream_query_progress(
    query_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    """
    Server-Sent Events stream for live agent progress.
    Connect with EventSource in the browser.

    Events:
    - agent_update: an agent started or completed
    - complete: pipeline finished successfully
    - error: pipeline failed
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        sent_count = 0
        timeout_seconds = 180  # 3-minute timeout
        start = time.time()

        # Send connection confirmation
        yield f"event: connected\ndata: {json.dumps({'query_id': query_id})}\n\n"

        while True:
            # Check timeout
            if time.time() - start > timeout_seconds:
                yield f"event: error\ndata: {json.dumps({'message': 'Pipeline timeout'})}\n\n"
                break

            # Send any new events
            events = _sse_events.get(query_id, [])
            while sent_count < len(events):
                event = events[sent_count]
                event_type = event.get("type", "agent_update")
                yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"
                sent_count += 1

                # If pipeline completed, close the stream
                if event_type in ("complete", "error"):
                    return

            await asyncio.sleep(0.5)  # Poll every 500ms

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get(
    "/{query_id}",
    summary="Get query status and results",
)
async def get_query(
    query_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get the current status and results of a query."""
    try:
        qid = uuid.UUID(query_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid query ID format")

    query_repo = QueryRepository(db)
    query = await query_repo.get_with_results(qid)

    if query is None:
        raise HTTPException(status_code=404, detail="Query not found")

    return {
        "id": str(query.id),
        "raw_query": query.raw_query,
        "status": query.status.value,
        "detected_language": query.detected_language,
        "parsed_constraints": query.parsed_constraints,
        "execution_time_ms": query.execution_time_ms,
        "error_message": query.error_message,
        "created_at": query.created_at.isoformat(),
        "completed_at": query.completed_at.isoformat() if query.completed_at else None,
        "results": [
            {
                "rank": r.rank,
                "supplier_id": str(r.supplier_id),
                "total_score": r.total_score,
                "constraint_score": r.constraint_score,
                "semantic_score": r.semantic_score,
                "proximity_score": r.proximity_score,
                "completeness_score": r.completeness_score,
                "compliance_matrix": r.compliance_matrix,
                "explanation": r.explanation,
                "distance_km": r.distance_km,
            }
            for r in (query.results or [])
        ],
    }


@router.get(
    "/{query_id}/audit",
    summary="Get full agent audit trail for a query",
)
async def get_audit_trail(
    query_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Returns the complete agent decision log for transparency."""
    try:
        qid = uuid.UUID(query_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid query ID")

    from sqlalchemy import select
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.query_id == qid)
        .order_by(AuditLog.timestamp)
    )
    logs = result.scalars().all()

    return {
        "query_id": query_id,
        "audit_entries": [
            {
                "agent_name": log.agent_name,
                "action": log.action,
                "reasoning": log.reasoning,
                "input_snapshot": log.input_snapshot,
                "output_snapshot": log.output_snapshot,
                "duration_ms": log.duration_ms,
                "timestamp": log.timestamp.isoformat(),
            }
            for log in logs
        ],
    }


async def _run_pipeline_background(
    query_id: str,
    raw_query: str,
    user_id: str,
) -> None:
    """
    Background task: runs the full agent pipeline and saves results.
    Called by FastAPI BackgroundTasks — runs after the HTTP response is sent.
    """
    from app.db.session import AsyncSessionLocal

    start_time = time.time()

    def _push_event(event_type: str, data: dict) -> None:
        """Push an SSE event to the buffer for this query."""
        if query_id in _sse_events:
            _sse_events[query_id].append({"type": event_type, **data})

    _push_event("agent_update", {
        "agent": "orchestrator",
        "status": "started",
        "message": "Pipeline starting...",
    })

    try:
        # Run the full agent pipeline
        final_state = await run_pipeline(raw_query, query_id, user_id)
        execution_time_ms = int((time.time() - start_time) * 1000)

        # Save results to database
        async with AsyncSessionLocal() as db:
            from sqlalchemy import update

            # Update query status
            q_update = {
                "status": QueryStatus.completed if not final_state.get("error") else QueryStatus.failed,
                "detected_language": final_state.get("detected_language", "en"),
                "parsed_constraints": final_state.get("parsed_constraints"),
                "execution_time_ms": execution_time_ms,
                "completed_at": datetime.now(timezone.utc),
            }
            if final_state.get("error"):
                q_update["error_message"] = final_state["error"]

            await db.execute(
                update(Query).where(Query.id == uuid.UUID(query_id)).values(**q_update)
            )

            # Save ranked results
            for ranked in final_state.get("ranked_suppliers", []):
                result = QueryResult(
                    query_id=uuid.UUID(query_id),
                    supplier_id=uuid.UUID(ranked["supplier_id"]),
                    rank=ranked["rank"],
                    total_score=ranked["total_score"],
                    constraint_score=ranked["constraint_score"],
                    semantic_score=ranked["semantic_score"],
                    proximity_score=ranked.get("proximity_score"),
                    completeness_score=ranked["completeness_score"],
                    compliance_matrix=ranked["compliance_matrix"],
                    explanation=ranked["explanation"],
                    distance_km=ranked.get("distance_km"),
                )
                db.add(result)

            # Save audit logs
            for entry in final_state.get("audit_log", []):
                log = AuditLog(
                    query_id=uuid.UUID(query_id),
                    agent_name=entry["agent_name"],
                    action=entry["action"],
                    reasoning=entry.get("reasoning"),
                    input_snapshot={"summary": entry.get("input_summary", "")},
                    output_snapshot={"summary": entry.get("output_summary", "")},
                    duration_ms=entry.get("duration_ms", 0),
                )
                db.add(log)

            await db.commit()

        # Notify SSE subscribers
        if final_state.get("error"):
            _push_event("error", {"message": final_state["error"]})
        else:
            _push_event("complete", {
                "query_id": query_id,
                "result_count": len(final_state.get("ranked_suppliers", [])),
                "execution_time_ms": execution_time_ms,
                "pipeline_status": final_state.get("pipeline_status"),
            })

    except Exception as e:
        logger.exception("[background] Pipeline failed for query_id=%s: %s", query_id, e)
        _push_event("error", {"message": f"Pipeline error: {str(e)}"})

        async with AsyncSessionLocal() as db:
            from sqlalchemy import update
            await db.execute(
                update(Query)
                .where(Query.id == uuid.UUID(query_id))
                .values(
                    status=QueryStatus.failed,
                    error_message=str(e),
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

    finally:
        # Clean up SSE buffer after 5 minutes
        await asyncio.sleep(300)
        _sse_events.pop(query_id, None)
