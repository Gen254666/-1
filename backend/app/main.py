from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.admin import admin_router, users_router
from app.api.points import router as points_router
from app.api.read import router as read_router
from app.auth.router import router as auth_router
from app.chat.router import router as chat_router
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.observability.router import router as observability_router


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.app_name)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        )

    app.include_router(auth_router)
    app.include_router(read_router)
    app.include_router(chat_router)
    app.include_router(points_router)
    app.include_router(admin_router)
    app.include_router(users_router)
    app.include_router(observability_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
