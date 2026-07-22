"""
app/middleware/request_id.py — Injects a unique X-Request-ID into every request.

WHY:
Without correlation IDs, tracing a single query through 6 agents and 50+ log
lines is impossible. This middleware stamps every request and propagates the ID
through the response headers so clients (and APM tools) can correlate logs.
"""

import contextvars
import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# Per-request ID, isolated per task/thread — concurrent requests each see their
# own value, unlike a filter added/removed on the shared root logger.
_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class _RequestIDFilter(logging.Filter):
    """Injects the current request's ID into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_ctx.get()
        return True


# Installed once at import time; reads the ContextVar per record.
logging.getLogger().addFilter(_RequestIDFilter())


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Assigns a unique request ID to every HTTP request.

    - Reads X-Request-ID from the incoming request if present (allows tracing
      from a gateway or load balancer that already assigned an ID).
    - Falls back to a newly generated UUID v4.
    - Writes the final ID back to the response as X-Request-ID.
    - Publishes the ID via a ContextVar read by a single logging.Filter so all
      agent logs are automatically tagged, safely under concurrency.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id

        token = _request_id_ctx.set(request_id)
        try:
            response: Response = await call_next(request)
        finally:
            _request_id_ctx.reset(token)

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
