"""Persistence operations for privacy-safe AI usage events."""

import uuid

from sqlalchemy.orm import Session

from app.db.models import AIUsageEvent
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
