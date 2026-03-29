"""Tests for db/retention.py — data retention policies."""
from __future__ import annotations

import sqlite3
import threading

from server.db.retention import (
    DEFAULT_RETENTION,
    get_retention,
    init_schema,
    set_retention,
)


def _make_db():
    conn = sqlite3.connect(":memory:")
    lock = threading.Lock()
    init_schema(conn)
    conn.commit()
    return conn, lock


def test_defaults_when_no_policy():
    conn, lock = _make_db()
    result = get_retention(conn, lock, "t1")
    assert result == DEFAULT_RETENTION


def test_set_and_get():
    conn, lock = _make_db()
    set_retention(conn, lock, "t1", metrics_days=7, audit_days=365, alerts_days=14, job_runs_days=60)
    result = get_retention(conn, lock, "t1")
    assert result == {
        "metrics_days": 7,
        "audit_days": 365,
        "alerts_days": 14,
        "job_runs_days": 60,
    }


def test_tenant_isolation():
    conn, lock = _make_db()
    set_retention(conn, lock, "t1", metrics_days=7)
    set_retention(conn, lock, "t2", metrics_days=180)
    r1 = get_retention(conn, lock, "t1")
    r2 = get_retention(conn, lock, "t2")
    assert r1["metrics_days"] == 7
    assert r2["metrics_days"] == 180


def test_upsert_overwrites():
    conn, lock = _make_db()
    set_retention(conn, lock, "t1", metrics_days=7, audit_days=30)
    set_retention(conn, lock, "t1", metrics_days=90, audit_days=365)
    result = get_retention(conn, lock, "t1")
    assert result["metrics_days"] == 90
    assert result["audit_days"] == 365
