"""Content-free AI usage recorders."""

import logging
from threading import Lock
from typing import Protocol

from app.db.repositories.ai_usage_repo import AIUsageRepository
from app.db.session import SyncSessionLocal
from app.platform.ai.types import AIUsageMeasurement

logger = logging.getLogger(__name__)


class AIUsageRecorder(Protocol):
    def record(self, measurement: AIUsageMeasurement) -> None: ...


class InMemoryAIUsageRecorder:
    def __init__(self) -> None:
        self._measurements: list[AIUsageMeasurement] = []
        self._lock = Lock()

    def record(self, measurement: AIUsageMeasurement) -> None:
        with self._lock:
            self._measurements.append(measurement)

    def snapshot(self) -> list[AIUsageMeasurement]:
        with self._lock:
            return list(self._measurements)


class DatabaseAIUsageRecorder:
    def record(self, measurement: AIUsageMeasurement) -> None:
        try:
            with SyncSessionLocal() as session:
                AIUsageRepository.record_sync(session, measurement)
        # Telemetry must report its own failure without turning a successful
        # provider response into an application error. This also covers invalid
        # optional identifiers supplied by diagnostics and service scripts.
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "AI usage persistence failed provider=%s operation=%s "
                "outcome=%s correlation_id=%s error_type=%s",
                measurement.provider,
                measurement.operation.value,
                measurement.outcome.value,
                measurement.correlation_id,
                type(exc).__name__,
            )


_PROCESS_AI_USAGE_RECORDER = DatabaseAIUsageRecorder()


def get_ai_usage_recorder() -> AIUsageRecorder:
    """Return the process-wide production recorder used by AI factories."""
    return _PROCESS_AI_USAGE_RECORDER
