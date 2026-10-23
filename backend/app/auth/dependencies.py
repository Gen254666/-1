from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import TokenError, decode_token
from app.core.db import get_db_session
from app.core.errors import ApiError
from app.core.redis import get_redis_client
from steel_core.db.enums import Role
from steel_core.db.models.accounts import User


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    redis: Any | None = Depends(get_redis_client),
) -> User:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError(401, "AUTH_TOKEN_INVALID", "缺少访问令牌")

    token = header.removeprefix("Bearer ").strip()
    try:
        payload = decode_token(token, expected_type="access")
    except TokenError as exc:
        raise ApiError(401, exc.code, exc.message) from exc

    jti = payload.get("jti")
    if redis is not None and jti:
        try:
            if await redis.get(f"sess:{jti}"):
                raise ApiError(401, "AUTH_TOKEN_INVALID", "令牌已注销")
        except ApiError:
            raise
        except Exception:  # noqa: BLE001
            pass

    user = await session.get(User, UUID(str(payload["sub"])))
    if user is None:
        raise ApiError(401, "AUTH_TOKEN_INVALID", "用户不存在")
    if not user.is_active:
        raise ApiError(403, "AUTH_ACCOUNT_DISABLED", "账号已停用")

    request.state.token_payload = payload
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.ADMIN:
        raise ApiError(403, "AUTH_FORBIDDEN", "需要管理员权限")
    return user
