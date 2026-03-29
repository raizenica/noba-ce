"""Tests for db.freeze: freeze_windows table and is_frozen logic."""
from __future__ import annotations
import sqlite3
import threading
import time
import pytest
from server.db.freeze import init_schema, add_window, list_windows, delete_window, is_frozen


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    init_schema(conn)
    return conn, lock


class TestFreezeWindows:
    def test_add_and_list(self, db):
        conn, lock = db
        now = int(time.time())
        add_window(conn, lock, tenant_id="default", name="Release freeze",
                   start_ts=now - 100, end_ts=now + 3600, created_by="admin",
                   reason="Planned release window")
        rows = list_windows(conn, lock, "default")
        assert len(rows) == 1
        assert rows[0]["name"] == "Release freeze"

    def test_is_frozen_true(self, db):
        conn, lock = db
        now = int(time.time())
        add_window(conn, lock, "default", "Active freeze",
                   now - 60, now + 3600, "admin", "test")
        assert is_frozen(conn, lock, "default") is True

    def test_is_frozen_false_outside_window(self, db):
        conn, lock = db
        now = int(time.time())
        add_window(conn, lock, "default", "Past freeze",
                   now - 7200, now - 3600, "admin", "expired")
        assert is_frozen(conn, lock, "default") is False

    def test_is_frozen_false_no_windows(self, db):
        conn, lock = db
        assert is_frozen(conn, lock, "default") is False

    def test_delete_window(self, db):
        conn, lock = db
        now = int(time.time())
        window_id = add_window(conn, lock, "default", "Temp",
                               now - 10, now + 60, "admin", "")
        delete_window(conn, lock, window_id)
        assert is_frozen(conn, lock, "default") is False

    def test_different_tenants_isolated(self, db):
        conn, lock = db
        now = int(time.time())
        add_window(conn, lock, "tenant-a", "Freeze A",
                   now - 60, now + 3600, "admin", "")
        assert is_frozen(conn, lock, "tenant-a") is True
        assert is_frozen(conn, lock, "tenant-b") is False
