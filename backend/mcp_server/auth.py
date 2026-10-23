from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt

from app.core.config import get_settings
from mcp_server.context import UserContext
from steel_core.db.enums import Role

AUDIENCE = "mcp-server"


class ServiceTokenError(Exception):
    pass


def create_service_token(*, user_id: UUID, role: Role, ttl_seconds: int = 60) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "type": "service",
        "aud": AUDIENCE,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.mcp_service_secret, algorithm=settings.jwt_algorithm)


def decode_service_token(token: str) -> UserContext:
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.mcp_service_secret,
            algorithms=[settings.jwt_algorithm],
            audience=AUDIENCE,
        )
    except jwt.ExpiredSignatureError as exc:
        raise ServiceTokenError("AUTH_TOKEN_EXPIRED") from exc
    except jwt.InvalidTokenError as exc:
        raise ServiceTokenError("AUTH_TOKEN_INVALID") from exc

    if payload.get("type") != "service":
        raise ServiceTokenError("AUTH_TOKEN_INVALID")
    try:
        return UserContext(
            user_id=UUID(str(payload["sub"])),
            role=Role(str(payload["role"])),
        )
    except (KeyError, ValueError) as exc:
        raise ServiceTokenError("AUTH_TOKEN_INVALID") from exc
