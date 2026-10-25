from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import TokenError, create_token, decode_token
from app.core.config import get_settings
from app.core.errors import ApiError
from steel_core.db.models.accounts import User, UserSession
from steel_core.security import hash_password, verify_password


@dataclass
class AuthResult:
    user: User
    access_token: str
    refresh_token: str
    expires_in: int


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def login(session: AsyncSession, *, username: str, password: str) -> AuthResult:
    settings = get_settings()
    now = datetime.now(UTC)
    user = await session.scalar(select(User).where(User.username == username.strip()))

    if user is None:
        raise ApiError(401, "AUTH_INVALID_CREDENTIALS", "用户名或密码错误")
    if user.locked_until is not None and user.locked_until > now:
        raise ApiError(423, "AUTH_ACCOUNT_LOCKED", "账号已锁定，请稍后再试")
    if not user.is_active:
        raise ApiError(403, "AUTH_ACCOUNT_DISABLED", "账号已停用")

    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_max_failures:
            user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
            await session.commit()
            raise ApiError(423, "AUTH_ACCOUNT_LOCKED", "登录失败次数过多，账号已锁定")
        await session.commit()
        raise ApiError(401, "AUTH_INVALID_CREDENTIALS", "用户名或密码错误")

    user.failed_login_count = 0
    user.locked_until = None
    result = await _issue_tokens(session, user)
    await session.commit()
    return result


async def refresh(session: AsyncSession, *, refresh_token: str) -> AuthResult:
    now = datetime.now(UTC)
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise ApiError(401, exc.code, exc.message) from exc

    token_hash = hash_refresh_token(refresh_token)
    stored = await session.scalar(
        select(UserSession).where(UserSession.refresh_token_hash == token_hash)
    )

    if stored is None or stored.revoked_at is not None:
        user_id = UUID(str(payload["sub"]))
        await session.execute(
            update(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await session.commit()
        raise ApiError(401, "AUTH_REFRESH_REUSED", "刷新令牌已失效，请重新登录")

    if stored.expires_at <= now:
        raise ApiError(401, "AUTH_TOKEN_EXPIRED", "刷新令牌已过期")

    settings = get_settings()
    last_used = stored.last_used_at or stored.created_at
    if now - last_used > timedelta(minutes=settings.session_idle_minutes):
        stored.revoked_at = now
        await session.commit()
        raise ApiError(401, "AUTH_SESSION_EXPIRED", "会话已超时，请重新登录")

    user = await session.get(User, stored.user_id)
    if user is None:
        raise ApiError(401, "AUTH_TOKEN_INVALID", "用户不存在")
    if not user.is_active:
        raise ApiError(403, "AUTH_ACCOUNT_DISABLED", "账号已停用")

    stored.revoked_at = now
    result = await _issue_tokens(session, user)
    await session.commit()
    return result


async def logout(
    session: AsyncSession,
    redis: Any | None,
    *,
    access_payload: dict[str, Any],
    refresh_token: str | None,
) -> None:
    jti = access_payload.get("jti")
    expires_at = access_payload.get("exp")
    if redis is not None and jti and expires_at:
        ttl = max(int(expires_at - datetime.now(UTC).timestamp()), 1)
        try:
            await redis.set(f"sess:{jti}", "1", ex=ttl)
        except Exception:  # noqa: BLE001
            pass

    if refresh_token:
        token_hash = hash_refresh_token(refresh_token)
        stored = await session.scalar(
            select(UserSession).where(UserSession.refresh_token_hash == token_hash)
        )
        if stored is not None and stored.revoked_at is None:
            stored.revoked_at = datetime.now(UTC)
            await session.commit()


async def change_password(
    session: AsyncSession,
    *,
    user: User,
    old_password: str,
    new_password: str,
) -> None:
    if not verify_password(user.password_hash, old_password):
        raise ApiError(400, "INVALID_PASSWORD", "原密码错误")
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    await session.commit()


async def _issue_tokens(session: AsyncSession, user: User) -> AuthResult:
    settings = get_settings()
    now = datetime.now(UTC)
    access_token, _, _ = create_token(
        user_id=user.id,
        token_type="access",
        role=user.role.value,
        expires_delta=timedelta(minutes=settings.access_token_minutes),
    )
    refresh_token, _, refresh_expires = create_token(
        user_id=user.id,
        token_type="refresh",
        role=user.role.value,
        expires_delta=timedelta(days=settings.refresh_token_days),
    )
    session.add(
        UserSession(
            user_id=user.id,
            refresh_token_hash=hash_refresh_token(refresh_token),
            expires_at=refresh_expires,
            last_used_at=now,
        )
    )
    return AuthResult(
        user=user,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_minutes * 60,
    )
