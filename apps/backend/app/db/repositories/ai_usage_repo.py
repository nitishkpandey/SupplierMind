"""Persistence operations for privacy-safe AI usage events."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.models import AIUsageEvent

if TYPE_CHECKING:
    from app.platform.ai.types import AIUsageMeasurement


class AIUsageRepository:
    @staticmethod
    def record_sync(
        session: Session,
        measurement: AIUsageMeasurement,
    ) -> None:
        event = AIUsageEvent(
            query_id=(
                uuid.UUID(measurement.query_id)
                if measurement.query_id
                else None
            ),
            user_id=(
                uuid.UUID(measurement.user_id)
                if measurement.user_id
                else None
            ),
            job_id=(
                uuid.UUID(measurement.job_id)
                if measurement.job_id
                else None
            ),
            source_document_id=(
                uuid.UUID(measurement.source_document_id)
                if measurement.source_document_id
                else None
            ),
            correlation_id=measurement.correlation_id,
            purpose=measurement.purpose,
            classification=measurement.classification.value,
            operation=measurement.operation.value,
            provider=measurement.provider,
            model=measurement.model,
            input_units=measurement.input_units,
            output_units=measurement.output_units,
            cost_usd=measurement.cost_usd,
            latency_ms=measurement.latency_ms,
            outcome=measurement.outcome.value,
            redaction_applied=measurement.redaction_applied,
            excerpted=measurement.excerpted,
            error_code=measurement.error_code,
        )
        session.add(event)
        session.commit()

    @staticmethod
    def known_query_cost_sync(
        session: Session,
        query_id: str,
    ) -> Decimal:
        statement = select(
            func.coalesce(func.sum(AIUsageEvent.cost_usd), 0)
        ).where(AIUsageEvent.query_id == uuid.UUID(query_id))
        total = session.scalar(statement)
        return Decimal(str(total or 0))

    @staticmethod
    async def summary_async(
        session: AsyncSession,
        window_hours: int,
    ) -> dict:
        row = (
            await session.execute(
                text(
                    """
                    SELECT
                        COUNT(*) AS calls,
                        COALESCE(SUM(input_units), 0) AS input_units,
                        COALESCE(SUM(output_units), 0) AS output_units,
                        COALESCE(SUM(cost_usd), 0) AS known_cost_usd,
                        COUNT(*) FILTER (
                            WHERE cost_usd IS NULL
                              AND outcome NOT IN (
                                  'denied',
                                  'budget_exceeded'
                              )
                        ) AS unknown_cost_calls,
                        COUNT(*) FILTER (
                            WHERE outcome IN ('denied', 'budget_exceeded')
                        ) AS denied_calls,
                        COUNT(*) FILTER (
                            WHERE outcome = 'error'
                        ) AS failed_calls
                    FROM ai_usage_events
                    WHERE created_at >
                        NOW() - make_interval(hours => :hours)
                    """
                ),
                {"hours": window_hours},
            )
        ).one()
        return {
            "calls": int(row.calls or 0),
            "input_units": int(row.input_units or 0),
            "output_units": int(row.output_units or 0),
            "known_cost_usd": float(row.known_cost_usd or 0),
            "unknown_cost_calls": int(row.unknown_cost_calls or 0),
            "denied_calls": int(row.denied_calls or 0),
            "failed_calls": int(row.failed_calls or 0),
        }

    @staticmethod
    async def provider_usage_async(
        session: AsyncSession,
        window_hours: int,
    ) -> list[dict]:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT
                        provider,
                        model,
                        operation,
                        COUNT(*) AS calls,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (
                            ORDER BY latency_ms
                        ) AS p95_ms,
                        COALESCE(SUM(cost_usd), 0) AS known_cost_usd,
                        COUNT(*) FILTER (
                            WHERE cost_usd IS NULL
                              AND outcome NOT IN (
                                  'denied',
                                  'budget_exceeded'
                              )
                        ) AS unknown_cost_calls
                    FROM ai_usage_events
                    WHERE created_at >
                        NOW() - make_interval(hours => :hours)
                    GROUP BY provider, model, operation
                    ORDER BY calls DESC, provider, model, operation
                    """
                ),
                {"hours": window_hours},
            )
        ).all()
        return [
            {
                "provider": row.provider,
                "model": row.model,
                "operation": row.operation,
                "calls": int(row.calls or 0),
                "p95_ms": int(row.p95_ms or 0),
                "known_cost_usd": float(row.known_cost_usd or 0),
                "unknown_cost_calls": int(
                    row.unknown_cost_calls or 0
                ),
            }
            for row in rows
        ]

    @staticmethod
    async def purpose_usage_async(
        session: AsyncSession,
        window_hours: int,
    ) -> list[dict]:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT
                        purpose,
                        COUNT(*) AS calls,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (
                            ORDER BY latency_ms
                        ) AS p95_ms,
                        COALESCE(SUM(cost_usd), 0) AS known_cost_usd,
                        COUNT(*) FILTER (
                            WHERE outcome IN (
                                'denied',
                                'budget_exceeded'
                            )
                        ) AS denied_calls,
                        COUNT(*) FILTER (
                            WHERE outcome = 'error'
                        ) AS failed_calls
                    FROM ai_usage_events
                    WHERE created_at >
                        NOW() - make_interval(hours => :hours)
                    GROUP BY purpose
                    ORDER BY calls DESC, purpose
                    """
                ),
                {"hours": window_hours},
            )
        ).all()
        return [
            {
                "purpose": row.purpose,
                "calls": int(row.calls or 0),
                "p95_ms": int(row.p95_ms or 0),
                "known_cost_usd": float(row.known_cost_usd or 0),
                "denied_calls": int(row.denied_calls or 0),
                "failed_calls": int(row.failed_calls or 0),
            }
            for row in rows
        ]

    @staticmethod
    async def top_queries_async(
        session: AsyncSession,
        window_hours: int,
    ) -> list[dict]:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT
                        query_id,
                        COUNT(*) AS calls,
                        COALESCE(SUM(cost_usd), 0) AS known_cost_usd,
                        COUNT(*) FILTER (
                            WHERE cost_usd IS NULL
                              AND outcome NOT IN (
                                  'denied',
                                  'budget_exceeded'
                              )
                        ) AS unknown_cost_calls
                    FROM ai_usage_events
                    WHERE created_at >
                        NOW() - make_interval(hours => :hours)
                      AND query_id IS NOT NULL
                    GROUP BY query_id
                    HAVING COUNT(cost_usd) > 0
                    ORDER BY known_cost_usd DESC
                    LIMIT 10
                    """
                ),
                {"hours": window_hours},
            )
        ).all()
        return [
            {
                "query_id": str(row.query_id),
                "calls": int(row.calls or 0),
                "known_cost_usd": float(row.known_cost_usd or 0),
                "unknown_cost_calls": int(
                    row.unknown_cost_calls or 0
                ),
            }
            for row in rows
        ]
