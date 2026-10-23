from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import get_settings


class TokenError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def create_token(
    *,
    user_id: uuid.UUID,
    token_type: str,
    role: str,
    expires_delta: timedelta,
) -> tuple[str, str, datetime]:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + expires_delta
    jti = uuid.uuid4().hex
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "role": role,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti, expires_at


def decode_token(token: str, *, expected_type: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("AUTH_TOKEN_EXPIRED", "令牌已过期") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("AUTH_TOKEN_INVALID", "令牌无效") from exc

    if payload.get("type") != expected_type:
        raise TokenError("AUTH_TOKEN_INVALID", "令牌类型不正确")
    return payload
