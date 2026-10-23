from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.app_name)
    app.add_middleware(RequestContextMiddleware)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
