"""Structured JSON logging with secret redaction.

Uses the standard library ``logging`` module with a JSON formatter to keep
dependencies minimal. A filter scrubs common secret-bearing keys and any value
that looks like a connection string so credentials never reach the logs.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

_SECRET_KEY_PATTERN = re.compile(
    r"(password|passwd|pwd|secret|token|access[_-]?key|api[_-]?key|"
    r"connection[_-]?string|conn[_-]?str|dsn)",
    re.IGNORECASE,
)

# Matches "user:password@host" credential segments inside URIs / DSNs.
_URI_CREDENTIALS = re.compile(r"(?P<scheme>://)(?P<user>[^:/@\s]+):(?P<pwd>[^@/\s]+)@")

_REDACTED = "***REDACTED***"

# Standard LogRecord attributes we do not want to duplicate into the JSON payload.
_RESERVED_ATTRS = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName",
    }
)


def redact(value: Any) -> Any:
    """Recursively redact secret-bearing keys and inline credentials."""
    if isinstance(value, dict):
        return {
            k: (_REDACTED if _SECRET_KEY_PATTERN.search(str(k)) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(redact(v) for v in value)
    if isinstance(value, str):
        return _URI_CREDENTIALS.sub(r"\g<scheme>\g<user>:" + _REDACTED + "@", value)
    return value


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, val in record.__dict__.items():
            if key not in _RESERVED_ATTRS and not key.startswith("_"):
                payload[key] = redact(val)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging with the JSON formatter. Idempotent."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


def get_logger(name: str) -> logging.LoggerAdapter:
    """Return a logger that always redacts structured ``extra`` fields."""
    return _RedactingAdapter(logging.getLogger(name), {})


class _RedactingAdapter(logging.LoggerAdapter):
    """Redacts the ``extra`` mapping before it reaches the formatter."""

    def process(self, msg: Any, kwargs: Any) -> tuple[Any, Any]:
        if "extra" in kwargs and isinstance(kwargs["extra"], dict):
            kwargs["extra"] = redact(kwargs["extra"])
        return msg, kwargs
