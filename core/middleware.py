import time
import uuid

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.config import get_settings
from core.logging import bind_request_context, clear_context
from core.rate_limit import check_rate_limit, rate_limit_remaining

logger = structlog.get_logger("middleware")

_RATE_LIMIT_EXEMPT = {"/health", "/metrics", "/", "/api/auth/login"}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        clear_context()
        bind_request_context(request_id, request.url.path, request.method)

        t0 = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - t0) * 1000)

        response.headers["X-Request-ID"] = request_id
        logger.info("request", status=response.status_code, duration_ms=duration_ms)
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _RATE_LIMIT_EXEMPT:
            return await call_next(request)

        redis = request.app.state.redis
        settings = get_settings()
        ip = request.client.host if request.client else "unknown"

        allowed = await check_rate_limit(redis, ip, settings.rate_limit_per_minute)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Retry in 60 seconds."},
                headers={"X-RateLimit-Remaining": "0"},
            )

        response = await call_next(request)
        remaining = await rate_limit_remaining(redis, ip, settings.rate_limit_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
