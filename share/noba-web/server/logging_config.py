"""Noba – Structured logging configuration.

Set NOBA_LOG_LEVEL=DEBUG/INFO/WARNING/ERROR to control verbosity.
Set NOBA_LOG_FORMAT=json to emit structured JSON logs.
"""
from __future__ import annotations

import json
import logging
import os
import time


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        exc_text = None
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
        payload: dict = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if exc_text:
            payload["exception"] = exc_text
        if hasattr(record, "extra_fields") and record.extra_fields:  # type: ignore[attr-defined]
            payload.update(record.extra_fields)  # type: ignore[attr-defined]
        return json.dumps(payload)


def setup_logging() -> None:
    """Configure root logger from NOBA_LOG_LEVEL and NOBA_LOG_FORMAT env vars."""
    level_name = os.environ.get("NOBA_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    use_json = os.environ.get("NOBA_LOG_FORMAT", "").lower() == "json"

    handler = logging.StreamHandler()
    if use_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

    root = logging.getLogger()
    root.setLevel(level)
    # Remove existing handlers to avoid duplicate output
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(handler)
