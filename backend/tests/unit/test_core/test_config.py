import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "APP_NAME",
        "ENVIRONMENT",
        "LOG_LEVEL",
        "DATABASE_URL_AGENT",
        "DATABASE_URL_MCP",
        "REDIS_URL",
        "JWT_SECRET",
        "MCP_BASE_URL",
        "MCP_SERVICE_SECRET",
        "CORS_ORIGINS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_defaults_are_dev_friendly() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.app_name == "steel-market-agent"
    assert settings.environment == "dev"
    assert "steel_market" in settings.database_url_agent
    assert settings.database_url_agent != settings.database_url_mcp


def test_prod_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="prod")  # type: ignore[call-arg]


def test_prod_accepts_explicit_secrets() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        environment="prod",
        jwt_secret="prod-jwt-secret-0123456789abcdef",
        mcp_service_secret="prod-mcp-secret-0123456789abcdef",
        cors_origins=["https://steel.example.com"],
    )

    assert settings.environment == "prod"


def test_prod_rejects_placeholder_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            environment="prod",
            jwt_secret="CHANGE_ME",
            mcp_service_secret="prod-mcp-secret-0123456789abcdef",
        )
