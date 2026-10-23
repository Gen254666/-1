import json
import logging
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "api_key",
        "jwt",
        "cookie",
        "set-cookie",
    }
)

_STANDARD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
        "asctime",
    }
)


def redact_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in SENSITIVE_KEYS:
            result[key] = "***"
        elif isinstance(value, Mapping):
            result[key] = redact_mapping(value)
        elif isinstance(value, list):
            result[key] = [
                redact_mapping(item) if isinstance(item, Mapping) else item for item in value
            ]
        else:
            result[key] = value
    return result


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_var.get()),
        }
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_ATTRS and key != "request_id"
        }
        payload.update(redact_mapping(extra))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if not any(isinstance(handler.formatter, JsonFormatter) for handler in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    root.setLevel(level.upper())
