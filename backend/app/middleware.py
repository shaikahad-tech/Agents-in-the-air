"""Middleware: rate limiting, structured request logging, global exception handler.

- ``RateLimitMiddleware``: in-memory sliding-window rate limiter per client IP.
  Resets every ``window`` seconds, allows ``limit`` requests per window.
  Returns 429 with a Retry-After header on exceed.

- ``RequestLoggingMiddleware``: structured JSON access log with method, path,
  status, duration, and client IP.

- ``global_exception_handler``: catches unhandled exceptions, logs the
  traceback, and returns a clean 500 JSON response (never leaks internals
  in production).
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from threading import Lock

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .config import Settings, get_settings

log = logging.getLogger("aita.middleware")


# ─── Rate limiting ────────────────────────────────────────────────────────


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory sliding-window rate limiter keyed by client IP.

    Good enough for single-instance deployments. For multi-instance prod,
    swap the counter for Redis.
    """

    def __init__(self, app: ASGIApp, settings: Settings):
        super().__init__(app)
        self.enabled = settings.rate_limit_enabled
        self.limit = settings.rate_limit_requests
        self.window = settings.rate_limit_window
        self._counts: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not self.enabled:
            return await call_next(request)

        # Only rate-limit API routes, not static assets
        if not request.url.path.startswith("/api"):
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        now = time.time()
        cutoff = now - self.window

        with self._lock:
            hits = self._counts[client]
            # prune old hits
            self._counts[client] = [t for t in hits if t > cutoff]
            if len(self._counts[client]) >= self.limit:
                retry = int(self.window - (now - self._counts[client][0]))
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": f"Rate limit exceeded: {self.limit} requests per {self.window}s.",
                        "retry_after": max(retry, 1),
                    },
                    headers={"Retry-After": str(max(retry, 1))},
                )
            self._counts[client].append(now)

        return await call_next(request)


# ─── Structured request logging ───────────────────────────────────────────


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every request as a structured JSON line with duration + status."""

    def __init__(self, app: ASGIApp, settings: Settings):
        super().__init__(app)
        self.env = settings.env

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.time()
        client = request.client.host if request.client else "-"
        method = request.method
        path = request.url.path

        try:
            response = await call_next(request)
            duration_ms = round((time.time() - start) * 1000, 2)
            log.info(
                json.dumps({
                    "method": method,
                    "path": path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                    "client": client,
                })
            )
            # Add response time header for observability
            response.headers["X-Response-Time-ms"] = str(duration_ms)
            return response
        except Exception as e:
            duration_ms = round((time.time() - start) * 1000, 2)
            log.error(
                json.dumps({
                    "method": method,
                    "path": path,
                    "status": 500,
                    "duration_ms": duration_ms,
                    "client": client,
                    "error": str(e),
                }),
                exc_info=True,
            )
            raise


# ─── Global exception handler ────────────────────────────────────────────


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions. Never leaks tracebacks in prod."""
    log.exception("Unhandled exception on %s %s", request.method, request.url.path)
    settings = get_settings()
    detail = str(exc) if settings.env != "production" else "Internal server error"
    return JSONResponse(
        status_code=500,
        content={
            "detail": detail,
            "status": "error",
            "path": request.url.path,
        },
    )
