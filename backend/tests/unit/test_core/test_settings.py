import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_prod_rejects_short_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("JWT_SECRET", "short")
    monkeypatch.setenv("MCP_SERVICE_SECRET", "m" * 48)
    monkeypatch.setenv("CORS_ORIGINS", '["https://steel.example.com"]')

    with pytest.raises(ValidationError):
        Settings()


def test_prod_rejects_localhost_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("JWT_SECRET", "j" * 48)
    monkeypatch.setenv("MCP_SERVICE_SECRET", "m" * 48)
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:5173"]')

    with pytest.raises(ValidationError):
        Settings()


def test_prod_rejects_http_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("JWT_SECRET", "j" * 48)
    monkeypatch.setenv("MCP_SERVICE_SECRET", "m" * 48)
    monkeypatch.setenv("CORS_ORIGINS", '["http://steel.example.com"]')

    with pytest.raises(ValidationError):
        Settings()


def test_prod_rejects_wildcard_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("JWT_SECRET", "j" * 48)
    monkeypatch.setenv("MCP_SERVICE_SECRET", "m" * 48)
    monkeypatch.setenv("CORS_ORIGINS", '["*"]')

    with pytest.raises(ValidationError):
        Settings()


def test_access_token_cannot_exceed_idle_timeout() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            access_token_minutes=120,
            session_idle_minutes=60,
        )


def test_prod_allows_domain_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("JWT_SECRET", "j" * 48)
    monkeypatch.setenv("MCP_SERVICE_SECRET", "m" * 48)
    monkeypatch.setenv("CORS_ORIGINS", '["https://steel.example.com"]')

    settings = Settings()

    assert settings.environment == "prod"
    assert settings.cors_origins == ["https://steel.example.com"]


def test_dev_allows_defaults() -> None:
    settings = Settings(environment="dev")

    assert settings.session_idle_minutes == 60
    assert settings.import_rate_limit == 5
    assert settings.llm_daily_request_limit == 200
    assert settings.llm_max_attempts_per_provider == 1
    assert settings.llm_max_total_attempts == 3
