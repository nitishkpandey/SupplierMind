"""
app/middleware/request_id.py — Injects a unique X-Request-ID into every request.

WHY:
Without correlation IDs, tracing a single query through 6 agents and 50+ log
lines is impossible. This middleware stamps every request and propagates the ID
through the response headers so clients (and APM tools) can correlate logs.
"""

import uuid
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Assigns a unique request ID to every HTTP request.

    - Reads X-Request-ID from the incoming request if present (allows tracing
      from a gateway or load balancer that already assigned an ID).
    - Falls back to a newly generated UUID v4.
    - Writes the final ID back to the response as X-Request-ID.
    - Injects the ID into every log record emitted during the request via a
      logging.Filter so all agent logs are automatically tagged.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id

        filter_ = _RequestIDFilter(request_id)
        root_logger = logging.getLogger()
        root_logger.addFilter(filter_)

        try:
            response: Response = await call_next(request)
        finally:
            root_logger.removeFilter(filter_)

        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class _RequestIDFilter(logging.Filter):
    """Injects request_id into every LogRecord emitted during a request."""

    def __init__(self, request_id: str) -> None:
        super().__init__()
        self.request_id = request_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = self.request_id
        return True
