"""
app/middleware/rate_limit.py — Sliding-window rate limiter per authenticated user.

In-memory implementation suitable for single-process deployments (development,
single-instance production). For multi-instance production, replace the
_windows dict with a Redis sliding-window counter (ZADD + ZRANGEBYSCORE).

Default limits (configurable via settings):
  - 20 requests per minute per user (identified by JWT sub claim or IP)
  - 429 Too Many Requests with Retry-After header on breach
"""

import logging
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60
_MAX_REQUESTS = 20

# { identity: deque of timestamps }
_windows: dict[str, deque] = defaultdict(deque)
_last_prune = 0.0


def _prune_windows(now: float) -> None:
    """Drop identities whose entire window has expired, so the dict is bounded
    by active clients rather than growing forever. Runs at most once per window.
    """
    global _last_prune
    if now - _last_prune < _WINDOW_SECONDS:
        return
    _last_prune = now
    cutoff = now - _WINDOW_SECONDS
    stale = [key for key, window in _windows.items() if not window or window[-1] < cutoff]
    for key in stale:
        del _windows[key]


def _get_identity(request: Request) -> str:
    """Extract user identity from JWT sub claim or fall back to client IP."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth.removeprefix("Bearer ")
        try:
            from app.core.security import decode_access_token
            payload = decode_access_token(token)
            return f"user:{payload['sub']}"
        except Exception:
            pass
    # Fallback: client IP. Behind a reverse proxy request.client.host is the
    # proxy, which would collapse every user into one bucket — prefer the first
    # hop of X-Forwarded-For when present.
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter.

    Exempt paths: /health, /docs, /openapi.json, /redoc — these should never
    be rate-limited as they are used by monitoring and tooling.
    """

    EXEMPT_PREFIXES = ("/health", "/docs", "/openapi.json", "/redoc")

    async def dispatch(self, request: Request, call_next):
        if any(request.url.path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return await call_next(request)

        identity = _get_identity(request)
        now = time.monotonic()
        _prune_windows(now)
        window = _windows[identity]

        # Drop timestamps outside the sliding window
        while window and window[0] < now - _WINDOW_SECONDS:
            window.popleft()

        if len(window) >= _MAX_REQUESTS:
            oldest = window[0]
            retry_after = int(_WINDOW_SECONDS - (now - oldest)) + 1
            logger.warning("[rate_limit] Throttled %s (%d req/%ds)", identity, _MAX_REQUESTS, _WINDOW_SECONDS)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={"Retry-After": str(retry_after)},
            )

        window.append(now)
        return await call_next(request)
