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
from app.core.config import settings
from app.db.models import Query, QueryResult, AuditLog, QueryStatus, User, UserRole
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
    logger.info("Received query submission from user_id=%s: %r", current_user.id, body.raw_query)
    # Validate query length
    if len(body.raw_query.strip()) < settings.QUERY_MIN_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Query too short. Minimum {settings.QUERY_MIN_LENGTH} characters.",
        )
    if len(body.raw_query) > settings.QUERY_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Query too long. Maximum {settings.QUERY_MAX_LENGTH} characters.",
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
        search_scope=body.search_scope,
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
        search_scope=body.search_scope,
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
    token: str | None = None,     # Accept JWT as query param for SSE
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Server-Sent Events stream for live agent progress.

    WHY TOKEN IN URL?
    The browser's EventSource API cannot send custom headers.
    Passing JWT as a query parameter is the standard workaround for SSE.

    SECURITY NOTE (documented in thesis):
    This is acceptable for a thesis prototype. In production, use a
    short-lived SSE-specific token (valid for 60 seconds, issued on query submit).

    Connect from JavaScript:
        const url = `/api/v1/queries/${id}/stream?token=${accessToken}`;
        const source = new EventSource(url);
    """
    # Validate token and enforce query ownership
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing access token")

    try:
        from app.core.security import decode_access_token
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    try:
        qid = uuid.UUID(query_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid query ID format")

    query_repo = QueryRepository(db)
    query = await query_repo.get_by_id(qid)
    if query is None:
        raise HTTPException(status_code=404, detail="Query not found")

    if query.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    async def event_generator() -> AsyncGenerator[str, None]:
        sent_count = 0
        timeout_seconds = settings.SSE_TIMEOUT_SECONDS
        start = time.time()

        # Connection confirmation
        yield f"event: connected\ndata: {json.dumps({'query_id': query_id})}\n\n"

        while True:
            if time.time() - start > timeout_seconds:
                yield f"event: error\ndata: {json.dumps({'message': f'Pipeline timeout after {timeout_seconds}s'})}\n\n"
                break

            events = _sse_events.get(query_id, [])
            while sent_count < len(events):
                event = events[sent_count]
                event_type = event.get("type", "agent_update")
                yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"
                sent_count += 1
                if event_type in ("complete", "error"):
                    return

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": settings.FRONTEND_URL,
        },
    )


@router.get(
    "",
    summary="Get query history for current user",
)
async def list_queries(
    offset: int = 0,
    limit: int = 20,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get paginated query history for the authenticated user."""
    from app.db.repositories.query_repo import QueryRepository
    from sqlalchemy import select, func

    query_repo = QueryRepository(db)
    queries = await query_repo.get_user_queries(current_user.id, offset=offset, limit=limit)

    # Count total
    result = await db.execute(
        select(func.count()).select_from(Query).where(Query.user_id == current_user.id)
    )
    total = result.scalar_one()

    return {
        "items": [
            {
                "id": str(q.id),
                "raw_query": q.raw_query,
                "status": q.status.value,
                "execution_time_ms": q.execution_time_ms,
                "created_at": q.created_at.isoformat(),
                "results": [{"rank": r.rank} for r in (q.results or [])],
            }
            for q in queries
        ],
        "total": total,
        "page": (offset // limit) + 1,
        "page_size": limit,
    }


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

    if query.user_id != current_user.id and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Enrich results with supplier details so the frontend avoids
    # a separate per-supplier fetch (which has no endpoint).
    from app.db.repositories.supplier_repo import SupplierRepository
    supplier_map: dict = {}
    if query.results:
        repo = SupplierRepository(db)
        sids = [r.supplier_id for r in query.results]
        suppliers = await repo.get_by_ids(sids)
        supplier_map = {str(s.id): s for s in suppliers}

    def _result_dict(r: QueryResult) -> dict:
        supplier = supplier_map.get(str(r.supplier_id))
        # Task 1.5: explanation is stored as a JSON structured object. Parse it
        # into explanation_detail; keep explanation as the plain summary string
        # (legacy rows hold plain text and pass through unchanged).
        explanation_text = r.explanation or ""
        explanation_detail = None
        if explanation_text:
            try:
                parsed = json.loads(explanation_text)
                if isinstance(parsed, dict) and "summary" in parsed:
                    explanation_detail = parsed
                    explanation_text = parsed.get("summary", "")
            except (ValueError, TypeError):
                pass  # legacy free-text explanation
        return {
            "rank": r.rank,
            "supplier_id": str(r.supplier_id),
            "supplier_name": supplier.name if supplier else None,
            "supplier_city": supplier.city if supplier else None,
            "supplier_country": supplier.country if supplier else None,
            "supplier_lat": float(supplier.latitude) if supplier and supplier.latitude else None,
            "supplier_lng": float(supplier.longitude) if supplier and supplier.longitude else None,
            "supplier_certifications": supplier.certifications if supplier else [],
            "supplier_capacity_value": supplier.capacity_value if supplier else None,
            "supplier_capacity_unit": supplier.capacity_unit if supplier else None,
            "supplier_lead_time_days": supplier.lead_time_days if supplier else None,
            "supplier_website": supplier.website if supplier else None,
            "supplier_source": supplier.source if supplier else None,
            "supplier_status": supplier.status.value if supplier else None,
            "tier": supplier.status.value if supplier else None,
            # Task 1.6: only present when screening couldn't complete; absence
            # means no pending state (we never assert "clear" in the UI).
            "sanctions_status": (
                (supplier.source_citations or {}).get("sanctions", {}).get("status")
                if supplier else None
            ),
            "total_score": r.total_score,
            "constraint_score": r.constraint_score,
            "semantic_score": r.semantic_score,
            "proximity_score": r.proximity_score,
            "completeness_score": r.completeness_score,
            "compliance_matrix": r.compliance_matrix,
            "explanation": explanation_text,
            "explanation_detail": explanation_detail,
            "distance_km": r.distance_km,
        }

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
        "results": [_result_dict(r) for r in (query.results or [])],
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
    query_repo = QueryRepository(db)
    query = await query_repo.get_by_id(qid)
    if query is None:
        raise HTTPException(status_code=404, detail="Query not found")

    if query.user_id != current_user.id and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

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
    search_scope: str,
) -> None:
    """
    Background task: runs the full agent pipeline and saves results.
    Sends SSE events to notify the frontend of progress.
    """
    from app.db.session import AsyncSessionLocal

    start_time = time.time()

    def _push(event_type: str, data: dict) -> None:
        if query_id in _sse_events:
            _sse_events[query_id].append({"type": event_type, **data})

    # Signal start
    _push("agent_update", {
        "agent": "orchestrator",
        "status": "started",
        "message": "Pipeline initializing...",
    })

    # Update query to processing
    async with AsyncSessionLocal() as db:
        from sqlalchemy import update
        await db.execute(
            update(Query)
            .where(Query.id == uuid.UUID(query_id))
            .values(status=QueryStatus.processing)
        )
        await db.commit()

    try:
        # Run the agent pipeline
        _push("agent_update", {"agent": "parser", "status": "running", "message": "Extracting constraints..."})
        final_state = await run_pipeline(raw_query, query_id, user_id, search_scope)
        execution_time_ms = int((time.time() - start_time) * 1000)

        # Push agent completion events from audit log
        for entry in final_state.get("audit_log", []):
            agent = entry.get("agent_name", "")
            _push("agent_update", {
                "agent": agent,
                "status": "done",
                "message": entry.get("output_summary", "")[:100],
                "duration_ms": entry.get("duration_ms", 0),
            })

        # Save results to database
        async with AsyncSessionLocal() as db:
            from sqlalchemy import update

            new_status = (
                QueryStatus.completed
                if not final_state.get("error")
                else QueryStatus.failed
            )

            await db.execute(
                update(Query)
                .where(Query.id == uuid.UUID(query_id))
                .values(
                    status=new_status,
                    detected_language=final_state.get("detected_language", "en"),
                    parsed_constraints=final_state.get("parsed_constraints"),
                    search_scope=final_state.get("search_scope", search_scope),
                    evaluator_retries=final_state.get("evaluator_retries", 0),
                    evaluator_verdict=final_state.get("evaluator_verdict"),
                    execution_time_ms=execution_time_ms,
                    completed_at=datetime.now(timezone.utc),
                    error_message=final_state.get("error"),
                )
            )

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

        # Signal completion
        if final_state.get("error"):
            _push("error", {"message": final_state["error"]})
        else:
            _push("complete", {
                "query_id": query_id,
                "result_count": len(final_state.get("ranked_suppliers", [])),
                "execution_time_ms": execution_time_ms,
            })

    except Exception as e:
        logger.exception("[background] Pipeline failed for query_id=%s", query_id)
        _push("error", {"message": f"Pipeline error: {str(e)[:200]}"})

        async with AsyncSessionLocal() as db:
            from sqlalchemy import update
            await db.execute(
                update(Query)
                .where(Query.id == uuid.UUID(query_id))
                .values(
                    status=QueryStatus.failed,
                    error_message=str(e)[:500],
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

    finally:
        await asyncio.sleep(settings.SSE_CLEANUP_DELAY_SECONDS)
        _sse_events.pop(query_id, None)
