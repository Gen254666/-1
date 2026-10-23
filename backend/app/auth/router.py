from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.dependencies import get_current_user
from app.auth.schemas import LoginRequest, TokenResponse, UserOut
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.errors import ApiError
from app.core.rate_limit import login_rate_limit
from app.core.redis import get_redis_client
from steel_core.db.models.accounts import User

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


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    _rate_limit: None = Depends(login_rate_limit),
) -> TokenResponse:
    result = await service.login(session, username=payload.username, password=payload.password)
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
    user: User = Depends(get_current_user),
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


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
