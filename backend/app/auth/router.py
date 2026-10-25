from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.dependencies import authenticate_user
from app.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    TokenResponse,
    UserOut,
)
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.errors import ApiError
from app.core.http import client_ip
from app.core.rate_limit import login_rate_limit
from app.core.redis import get_redis_client
from steel_core.audit.service import write_audit
from steel_core.db.models.accounts import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])
REFRESH_COOKIE = "refresh_token"
COOKIE_PATH = "/api/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        secure=settings.environment == "prod",
        samesite="strict",
        path=COOKIE_PATH,
    )


def _token_response(result: service.AuthResult) -> TokenResponse:
    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=UserOut.model_validate(result.user),
    )


async def _audit_login(
    session: AsyncSession,
    *,
    user_id: Any | None,
    action: str,
    username: str,
    ip: str | None,
    code: str | None = None,
) -> None:
    try:
        await write_audit(
            session,
            user_id=user_id,
            action=action,
            resource_type="auth",
            resource_id=str(user_id) if user_id else None,
            detail={"username": username[:100], "code": code},
            ip=ip,
        )
        await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("login audit failed")


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    _rate_limit: None = Depends(login_rate_limit),
) -> TokenResponse:
    ip = client_ip(request)
    try:
        result = await service.login(
            session, username=payload.username, password=payload.password
        )
    except ApiError as exc:
        await _audit_login(
            session,
            user_id=None,
            action="auth.login_failed",
            username=payload.username,
            ip=ip,
            code=exc.code,
        )
        raise
    await _audit_login(
        session,
        user_id=result.user.id,
        action="auth.login",
        username=result.user.username,
        ip=ip,
    )
    _set_refresh_cookie(response, result.refresh_token)
    return _token_response(result)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if not refresh_token:
        raise ApiError(401, "AUTH_TOKEN_INVALID", "缺少刷新令牌")
    result = await service.refresh(session, refresh_token=refresh_token)
    _set_refresh_cookie(response, result.refresh_token)
    return _token_response(result)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    redis: Any | None = Depends(get_redis_client),
    user: User = Depends(authenticate_user),
) -> Response:
    await service.logout(
        session,
        redis,
        access_payload=request.state.token_payload,
        refresh_token=request.cookies.get(REFRESH_COOKIE),
    )
    response = Response(status_code=204)
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    return response


@router.post("/change-password", status_code=204)
async def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(authenticate_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await service.change_password(
        session,
        user=user,
        old_password=payload.old_password,
        new_password=payload.new_password,
    )
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(authenticate_user)) -> UserOut:
    return UserOut.model_validate(user)
