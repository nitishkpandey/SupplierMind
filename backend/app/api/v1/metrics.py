"""
app/api/v1/metrics.py — Admin operational metrics from audit_logs.

Task 2.5. Reads the existing audit_logs table to surface per-agent latency
percentiles, throttle event counts, human-decision counts, and recent
errors over a configurable window. Adds no new instrumentation — every
metric is derived from data the system already produces.

Aggregation is done at the SQL layer (PERCENTILE_CONT, COUNT) so the
endpoint stays sub-second even after the audit_logs table grows.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.models import User
from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_WINDOW_HOURS = 168  # 1 week
RECENT_ERRORS_LIMIT = 10


@router.get(
    "/metrics",
    summary="Operational metrics for the last N hours (admin only)",
)
async def get_admin_metrics(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    window_hours: int = Query(24, ge=1, le=MAX_WINDOW_HOURS),
) -> dict:
    """
    Aggregate operational signal from audit_logs over the last `window_hours`.

    The dual purpose: (1) a 90-second visual answer to "is the system healthy"
    for thesis demos and viva questions, (2) a debugging surface for the
    builder. The throttle pacing-event count makes the Week 1 rate-limit work
    directly visible — that was opaque-to-stdout before this endpoint existed.
    """
    # ── Per-agent latency percentiles ─────────────────────────────────
    latency_rows = (
        await db.execute(
            text(
                """
                SELECT
                    agent_name,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95,
                    AVG(duration_ms) AS mean,
                    COUNT(*) AS cnt
                FROM audit_logs
                WHERE timestamp > NOW() - make_interval(hours => :hours)
                GROUP BY agent_name
                ORDER BY cnt DESC
                """
            ),
            {"hours": window_hours},
        )
    ).all()

    agent_latency = [
        {
            "agent_name": row.agent_name,
            "p50_ms": int(row.p50 or 0),
            "p95_ms": int(row.p95 or 0),
            "mean_ms": int(row.mean or 0),
            "count": int(row.cnt),
        }
        for row in latency_rows
    ]

    # ── Summary counts ───────────────────────────────────────────────
    summary_row = (
        await db.execute(
            text(
                """
                SELECT
                    COUNT(DISTINCT query_id) FILTER (WHERE query_id IS NOT NULL) AS queries,
                    COUNT(*) FILTER (WHERE agent_name != 'human_admin' AND agent_name != 'rate_limiter') AS agent_invocations,
                    COUNT(*) FILTER (WHERE agent_name = 'human_admin') AS human_decisions,
                    COUNT(DISTINCT query_id) FILTER (WHERE action = 'error') AS error_queries
                FROM audit_logs
                WHERE timestamp > NOW() - make_interval(hours => :hours)
                """
            ),
            {"hours": window_hours},
        )
    ).one()

    summary = {
        "total_queries": int(summary_row.queries or 0),
        "total_agent_invocations": int(summary_row.agent_invocations or 0),
        "total_human_decisions": int(summary_row.human_decisions or 0),
        "queries_with_errors": int(summary_row.error_queries or 0),
    }

    # ── Throttle events ──────────────────────────────────────────────
    throttle_row = (
        await db.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (WHERE agent_name = 'rate_limiter' AND action = 'pacing_event') AS pacing,
                    COUNT(*) FILTER (WHERE reasoning ILIKE '%429%') AS rate_429
                FROM audit_logs
                WHERE timestamp > NOW() - make_interval(hours => :hours)
                """
            ),
            {"hours": window_hours},
        )
    ).one()

    # Sanctions pending review is a current-state metric, not time-windowed —
    # if a supplier is sitting in pending_review, an operator cares regardless
    # of when sanctions screening last ran.
    sanctions_row = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) AS cnt
                FROM suppliers
                WHERE is_active = true
                  AND (source_citations -> 'sanctions' ->> 'status') = 'pending_review'
                """
            )
        )
    ).one()

    throttle_events = {
        "throttle_429_count": int(throttle_row.rate_429 or 0),
        "throttle_pacing_events": int(throttle_row.pacing or 0),
        "sanctions_pending_review": int(sanctions_row.cnt or 0),
    }

    # ── Recent errors ────────────────────────────────────────────────
    error_rows = (
        await db.execute(
            text(
                """
                SELECT timestamp, agent_name, action, query_id, reasoning
                FROM audit_logs
                WHERE timestamp > NOW() - make_interval(hours => :hours)
                  AND action IN ('error', 'no_web_results', 'clarification_needed', 'skipped_no_api_key')
                ORDER BY timestamp DESC
                LIMIT :lim
                """
            ),
            {"hours": window_hours, "lim": RECENT_ERRORS_LIMIT},
        )
    ).all()

    recent_errors = [
        {
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "agent_name": row.agent_name,
            "action": row.action,
            "query_id": str(row.query_id) if row.query_id else None,
            "reasoning": (row.reasoning or "")[:200],
        }
        for row in error_rows
    ]

    # Active LLM provider + running cost (Development Plan, Phase 1).
    from app.core.llm import get_llm_client

    try:
        llm = get_llm_client()
        llm_info = {
            "provider": getattr(llm, "provider_name", "unknown"),
            "last_provider_used": getattr(llm, "last_provider_used", None),
            "estimated_cost_usd": round(getattr(llm, "total_cost_usd", 0.0), 4),
        }
    except Exception as e:  # noqa: BLE001 — metrics must not 500 on LLM config issues
        llm_info = {"provider": "unavailable", "error": str(e)[:200]}

    return {
        "window_hours": window_hours,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "agent_latency": agent_latency,
        "throttle_events": throttle_events,
        "recent_errors": recent_errors,
        "llm": llm_info,
    }
