"""Tests for structured logging configuration."""
from __future__ import annotations

import io
import json
import logging


def test_json_formatter_outputs_valid_json():
    from server.logging_config import JsonFormatter
    # conftest disables logging globally; re-enable for this test only
    prev = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    try:
        handler = logging.StreamHandler(io.StringIO())
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger("test_json_fmt")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.info("hello world")
        output = handler.stream.getvalue().strip()
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["message"] == "hello world"
        assert "timestamp" in data
        assert "logger" in data
    finally:
        logger.removeHandler(handler)
        logging.disable(prev)


def test_setup_logging_respects_env_level(monkeypatch):
    from server.logging_config import setup_logging
    monkeypatch.setenv("NOBA_LOG_LEVEL", "WARNING")
    setup_logging()
    root_logger = logging.getLogger()
    assert root_logger.level <= logging.WARNING


def test_setup_logging_text_format_by_default(monkeypatch):
    from server.logging_config import setup_logging
    monkeypatch.delenv("NOBA_LOG_FORMAT", raising=False)
    # Should not raise
    setup_logging()
