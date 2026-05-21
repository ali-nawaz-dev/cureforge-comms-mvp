import json
import logging
import os
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Include any extra fields attached to the record
        standard_keys = {
            "args", "created", "exc_info", "exc_text", "filename", "funcName",
            "levelname", "levelno", "lineno", "message", "module", "msecs",
            "msg", "name", "pathname", "process", "processName", "relativeCreated",
            "stack_info", "thread", "threadName",
        }
        for key, value in record.__dict__.items():
            if key not in standard_keys:
                payload[key] = value
        return json.dumps(payload, sort_keys=True, default=str)


def configure_json_logging(level: str | None = None) -> None:
    """Configure root logger with JSON formatter.

    Level is taken from LOG_LEVEL env var, then from the `level` argument,
    then defaults to INFO. Safe to call multiple times.
    """
    effective_level = level or os.getenv("LOG_LEVEL", "INFO")
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(effective_level)

