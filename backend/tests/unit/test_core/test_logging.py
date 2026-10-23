import json
import logging

from app.core.logging import JsonFormatter, redact_mapping, request_id_var


def test_redact_mapping_hides_sensitive_values() -> None:
    result = redact_mapping(
        {
            "authorization": "Bearer secret",
            "password": "p",
            "path": "/api/quotes",
            "nested": {"token": "t", "ok": 1},
            "items": [{"api_key": "k", "name": "safe"}],
        }
    )

    assert result["authorization"] == "***"
    assert result["password"] == "***"
    assert result["path"] == "/api/quotes"
    assert result["nested"] == {"token": "***", "ok": 1}
    assert result["items"] == [{"api_key": "***", "name": "safe"}]


def test_json_formatter_includes_request_id_and_redacts() -> None:
    token = request_id_var.set("req-123")
    try:
        record = logging.LogRecord(
            name="steel.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        record.method = "GET"
        record.authorization = "Bearer secret"

        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)

    assert payload["level"] == "INFO"
    assert payload["logger"] == "steel.test"
    assert payload["message"] == "hello"
    assert payload["request_id"] == "req-123"
    assert payload["method"] == "GET"
    assert payload["authorization"] == "***"
    assert payload["timestamp"].endswith("+00:00")
