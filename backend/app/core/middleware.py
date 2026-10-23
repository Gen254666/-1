import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import request_id_var
from app.observability.metrics import REQUEST_COUNT, REQUEST_LATENCY

logger = logging.getLogger("app.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        token = request_id_var.set(request_id)
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_seconds = perf_counter() - started
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            REQUEST_COUNT.labels(method=request.method, path=path, status=str(status_code)).inc()
            REQUEST_LATENCY.labels(method=request.method, path=path).observe(duration_seconds)
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": round(duration_seconds * 1000, 2),
                    "request_id": request_id,
                },
            )
            request_id_var.reset(token)
