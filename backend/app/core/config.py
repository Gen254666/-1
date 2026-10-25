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
    data_rate_limit: int = 120
    import_rate_limit: int = 5
    rate_limit_window_seconds: int = 60
    session_idle_minutes: int = 60
    upload_tmp_dir: str = ""
    prod_allow_local_origins: bool = False
    mcp_base_url: str = "http://localhost:8001"
    mcp_service_secret: str = DEV_MCP_SERVICE_SECRET
    chroma_path: str = "../data/chroma"
    hf_endpoint: str = "https://hf-mirror.com"

    llm_fallback_order: str = "claude,deepseek,doubao"
    llm_timeout_seconds: float = 30.0
    llm_daily_request_limit: int = 200
    llm_max_attempts_per_provider: int = 1
    llm_max_total_attempts: int = 3
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    claude_model: str = "claude-sonnet-4-6"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    doubao_api_key: str = ""
    doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    doubao_model: str = ""
    chat_max_tool_calls: int = 8
    chat_max_tool_rounds: int = 4

    cors_origins: list[str] = ["http://localhost:5173"]

    @model_validator(mode="after")
    def _validate_prod_secrets(self) -> "Settings":
        if self.environment == "prod":
            for name, value in (
                ("JWT_SECRET", self.jwt_secret),
                ("MCP_SERVICE_SECRET", self.mcp_service_secret),
            ):
                if (
                    value in {DEV_JWT_SECRET, DEV_MCP_SERVICE_SECRET}
                    or value.startswith("CHANGE_ME")
                    or len(value) < 32
                ):
                    msg = f"{name} must be a non-placeholder value of at least 32 characters in production"
                    raise ValueError(msg)
            for origin in self.cors_origins:
                local = origin.startswith("http://localhost") or origin.startswith(
                    "http://127.0.0.1"
                )
                if local and self.prod_allow_local_origins:
                    continue
                if origin in {"*", "null"} or not origin.startswith("https://"):
                    msg = (
                        "CORS_ORIGINS must contain https origins only in production; "
                        "set PROD_ALLOW_LOCAL_ORIGINS=1 only for a local smoke test"
                    )
                    raise ValueError(msg)
        if self.access_token_minutes > self.session_idle_minutes:
            msg = "ACCESS_TOKEN_MINUTES must not exceed SESSION_IDLE_MINUTES"
            raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
