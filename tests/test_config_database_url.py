"""Tests for DATABASE_URL config value."""
from __future__ import annotations
import importlib


def test_database_url_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import server.config as cfg
    importlib.reload(cfg)
    assert cfg.DATABASE_URL == ""


def test_database_url_reads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    import server.config as cfg
    importlib.reload(cfg)
    assert cfg.DATABASE_URL == "postgresql://user:pass@localhost/db"
