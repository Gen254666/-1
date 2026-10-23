from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-change-me-32-bytes-minimum"
DEV_MCP_SERVICE_SECRET = "dev-only-mcp-secret-32-bytes-minimum"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "steel-market-agent"
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    database_url_agent: str = (
        "postgresql+asyncpg://steel_agent:steel_agent@localhost:5432/steel_market"
    )
    database_url_mcp: str = "postgresql+asyncpg://steel_mcp:steel_mcp@localhost:5432/steel_market"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    login_max_failures: int = 5
    login_lock_minutes: int = 15
    login_rate_limit: int = 5
    rate_limit_window_seconds: int = 60
    mcp_base_url: str = "http://localhost:8001"
    mcp_service_secret: str = DEV_MCP_SERVICE_SECRET
    chroma_path: str = "../data/chroma"

    cors_origins: list[str] = ["http://localhost:5173"]

    @model_validator(mode="after")
    def _validate_prod_secrets(self) -> "Settings":
        if self.environment == "prod":
            if self.jwt_secret == DEV_JWT_SECRET:
                msg = "JWT_SECRET must be set to a non-default value in production"
                raise ValueError(msg)
            if self.mcp_service_secret == DEV_MCP_SERVICE_SECRET:
                msg = "MCP_SERVICE_SECRET must be set to a non-default value in production"
                raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
