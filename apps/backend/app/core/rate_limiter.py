"""
app/core/rate_limiter.py — Proactive sliding-window throttle for the LLM client.

WHY: Firing LLM calls with no quota awareness means the first few succeed and
the rest get 429, after which tenacity backs off 2-15s per call. A single query
can spend most of its time in reactive backoff. This limiter paces requests to
stay under ~85% of the published per-model limits so 429s rarely happen at all.
The tenacity retry in llm.py stays as a backstop for the edge cases.

Sliding window, per model, tracking both RPM and TPM over a 60s window.
Thread-safe: multiple agent nodes may issue calls concurrently.
"""

import logging
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60.0

# Pace to this fraction of the published limit. Real limits have variance
# (clock skew, bursts, the retry backstop), so leave headroom. Start at 0.85;
# drop toward 0.75 if 429s persist, creep to 0.90 if queries feel slow.
SAFETY_MARGIN = 0.85

# Per-model API limits. OpenAI paid tier 1 (conservative vs the published
# 500 RPM / 200K TPM so bursts never 429). The Groq/llama entries were removed
# in Phase C (ADR-002); the prefix fallback in _caps resolves dated snapshots
# to their family.
MODEL_RATE_LIMITS: dict[str, dict[str, int]] = {
    "gpt-4o-mini": {"rpm": 400, "tpm": 180_000},
}

# Used when a model is not in MODEL_RATE_LIMITS — conservative so an unknown
# model under-throttles rather than 429-storms.
DEFAULT_LIMIT: dict[str, int] = {"rpm": 30, "tpm": 6_000}


class GroqRateLimiter:
    """Per-model sliding-window limiter. Call acquire() before each API call.

    Name retained for git-blame continuity; post-Phase-C this is a generic
    rate limiter (it throttles OpenAI). Proper rename deferred to post-thesis
    cleanup.
    """

    def __init__(
        self,
        limits: dict[str, dict[str, int]] | None = None,
        default_limit: dict[str, int] | None = None,
        margin: float = SAFETY_MARGIN,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        audit_writer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._limits = limits if limits is not None else MODEL_RATE_LIMITS
        self._default = default_limit if default_limit is not None else DEFAULT_LIMIT
        self._margin = margin
        self._monotonic = monotonic
        self._sleep = sleep
        # Optional callback invoked once per pacing event. Production wires this
        # to an audit_logs writer (see _default_audit_writer below) so the Week 1
        # throttle work is observable from the admin metrics page. Tests pass
        # None to keep the limiter pure.
        self._audit_writer = audit_writer
        self._lock = threading.Lock()
        # Per model: request timestamps and (timestamp, tokens) entries.
        self._request_log: dict[str, deque[float]] = defaultdict(deque)
        self._token_log: dict[str, deque[list]] = defaultdict(deque)

    def _caps(self, model: str) -> tuple[float, float]:
        limit = self._limits.get(model)
        if limit is None:
            # Prefix fallback: a dated snapshot (gpt-4o-mini-2024-07-18)
            # inherits its family's limits (gpt-4o-mini) so pinning the model
            # does not silently drop to the conservative default (Audit H).
            for family, lim in self._limits.items():
                if model.startswith(family):
                    limit = lim
                    break
        if limit is None:
            limit = self._default
        return limit["rpm"] * self._margin, limit["tpm"] * self._margin

    def _prune(self, model: str, now: float) -> None:
        cutoff = now - WINDOW_SECONDS
        rlog = self._request_log[model]
        while rlog and rlog[0] <= cutoff:
            rlog.popleft()
        tlog = self._token_log[model]
        while tlog and tlog[0][0] <= cutoff:
            tlog.popleft()

    def acquire(self, model: str, estimated_tokens: int = 0) -> float:
        """
        Block until issuing one request of `estimated_tokens` stays within the
        paced limits. Returns the request timestamp (pass it to
        update_actual_tokens once the real usage is known).
        """
        rpm_cap, tpm_cap = self._caps(model)
        with self._lock:
            while True:
                now = self._monotonic()
                self._prune(model, now)
                rlog = self._request_log[model]
                tlog = self._token_log[model]

                req_blocked = len(rlog) + 1 > rpm_cap
                token_sum = sum(entry[1] for entry in tlog)
                tok_blocked = token_sum + estimated_tokens > tpm_cap

                if not req_blocked and not tok_blocked:
                    break

                waits: list[float] = []
                if req_blocked and rlog:
                    waits.append(rlog[0] + WINDOW_SECONDS - now)
                if tok_blocked and tlog:
                    waits.append(tlog[0][0] + WINDOW_SECONDS - now)
                if not waits:
                    # Nothing to age out (e.g. a single request larger than the
                    # whole token budget). Let it through; the retry backstop
                    # handles the rare 429.
                    break

                wait = max(0.0, min(waits))
                wait_ms = int(wait * 1000)
                logger.info(
                    "[ratelimit] Pacing call: sleeping %dms for model %s "
                    "(current: %d rpm, %d tpm)",
                    wait_ms, model, len(rlog), token_sum,
                )
                self._sleep(wait)
                if self._audit_writer is not None:
                    try:
                        self._audit_writer(
                            {
                                "model": model,
                                "wait_ms": wait_ms,
                                "rpm": len(rlog),
                                "tpm": token_sum,
                            }
                        )
                    except Exception:
                        logger.warning(
                            "[ratelimit] audit_writer failed; pacing event not persisted",
                            exc_info=True,
                        )

            now = self._monotonic()
            self._request_log[model].append(now)
            self._token_log[model].append([now, estimated_tokens])
            return now

    def update_actual_tokens(self, model: str, timestamp: float, actual_tokens: int) -> None:
        """Replace the pre-call estimate with the real usage from the response."""
        with self._lock:
            for entry in self._token_log[model]:
                if entry[0] == timestamp:
                    entry[1] = actual_tokens
                    return


def _default_audit_writer(event: dict[str, Any]) -> None:
    """
    Persist one pacing event to audit_logs so the admin metrics page can
    surface throttle activity. Runs in the same thread as the limiter (we
    are already sleeping when this fires, so the DB write is hidden inside
    the pause). Swallows DB failures — observability must never break the
    pipeline.
    """
    # Late imports avoid a circular import: rate_limiter is pulled in by
    # llm.py very early in startup, before the DB layer is fully resolved.
    from app.db.models import AuditLog
    from app.db.session import SyncSessionLocal

    with SyncSessionLocal() as session:
        session.add(
            AuditLog(
                query_id=None,
                agent_name="rate_limiter",
                action="pacing_event",
                input_snapshot={"model": event["model"]},
                output_snapshot=event,
                reasoning=(
                    f"Paced {event['wait_ms']}ms for {event['model']} "
                    f"(rpm={event['rpm']}, tpm={event['tpm']})"
                ),
                duration_ms=event["wait_ms"],
            )
        )
        session.commit()


_limiter: GroqRateLimiter | None = None
_limiter_lock = threading.Lock()


def get_rate_limiter() -> GroqRateLimiter:
    """Process-wide singleton limiter shared across all agents/threads."""
    global _limiter
    if _limiter is None:
        with _limiter_lock:
            if _limiter is None:
                _limiter = GroqRateLimiter(audit_writer=_default_audit_writer)
    return _limiter
