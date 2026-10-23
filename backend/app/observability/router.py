from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.redis import get_redis_client

router = APIRouter(tags=["observability"])


@router.get("/metrics")
async def metrics_endpoint() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/readyz")
async def readyz_endpoint(
    session: AsyncSession = Depends(get_db_session),
    redis: Any | None = Depends(get_redis_client),
) -> Any:
    checks: dict[str, str] = {}
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        checks["database"] = "error"
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "checks": checks},
        )
    checks["database"] = "ok"

    if redis is None:
        checks["redis"] = "unavailable"
    else:
        try:
            await redis.ping()
            checks["redis"] = "ok"
        except Exception:  # noqa: BLE001
            checks["redis"] = "error"

    return {"status": "ready", "checks": checks}
