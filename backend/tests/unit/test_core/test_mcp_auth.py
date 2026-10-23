import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from mcp_server.auth import (
    AUDIENCE,
    ServiceTokenError,
    create_service_token,
    decode_service_token,
)
from steel_core.db.enums import Role


def test_service_token_roundtrip() -> None:
    user_id = uuid.uuid4()

    token = create_service_token(user_id=user_id, role=Role.ADMIN, ttl_seconds=60)
    context = decode_service_token(token)

    assert context.user_id == user_id
    assert context.role == Role.ADMIN


def test_service_token_rejects_wrong_audience() -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "user",
            "type": "service",
            "aud": "other-service",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=1)).timestamp()),
        },
        settings.mcp_service_secret,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(ServiceTokenError):
        decode_service_token(token)


def test_service_token_rejects_expired() -> None:
    token = create_service_token(user_id=uuid.uuid4(), role=Role.USER, ttl_seconds=-1)

    with pytest.raises(ServiceTokenError):
        decode_service_token(token)


def test_audience_constant() -> None:
    assert AUDIENCE == "mcp-server"
