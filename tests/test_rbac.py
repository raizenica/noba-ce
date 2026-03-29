"""Tests for db.rbac: resource_acls table."""
from __future__ import annotations

import sqlite3
import threading

import pytest

from server.db.rbac import delete_acl, get_acl, init_schema, list_acls, set_acl


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    lock = threading.Lock()
    init_schema(conn)
    return conn, lock


class TestRBACSchema:
    def test_set_and_get_acl(self, db):
        conn, lock = db
        set_acl(
            conn,
            lock,
            tenant_id="default",
            username="alice",
            resource_type="automations",
            can_read=True,
            can_write=False,
        )
        row = get_acl(conn, lock, "default", "alice", "automations")
        assert row is not None
        assert row["can_read"] == 1
        assert row["can_write"] == 0

    def test_list_acls_by_tenant(self, db):
        conn, lock = db
        set_acl(conn, lock, "t1", "alice", "automations", True, False)
        set_acl(conn, lock, "t1", "alice", "api_keys", True, True)
        set_acl(conn, lock, "t2", "bob", "automations", True, False)
        rows = list_acls(conn, lock, tenant_id="t1")
        assert len(rows) == 2

    def test_upsert_overwrites(self, db):
        conn, lock = db
        set_acl(conn, lock, "default", "alice", "automations", True, False)
        set_acl(conn, lock, "default", "alice", "automations", False, False)
        row = get_acl(conn, lock, "default", "alice", "automations")
        assert row["can_read"] == 0

    def test_delete_acl(self, db):
        conn, lock = db
        set_acl(conn, lock, "default", "alice", "automations", True, True)
        delete_acl(conn, lock, "default", "alice", "automations")
        assert get_acl(conn, lock, "default", "alice", "automations") is None

    def test_no_acl_returns_none(self, db):
        conn, lock = db
        assert get_acl(conn, lock, "default", "bob", "integrations") is None


class TestRBACMixin:
    def test_mixin_set_and_get(self):
        """Verify _RBACMixin delegates to module functions with correct conn routing."""
        from server.db.rbac import _RBACMixin

        conn = sqlite3.connect(":memory:")
        lock = threading.Lock()
        init_schema(conn)

        class FakeDB(_RBACMixin):
            def _get_conn(self):
                return conn

            def _get_read_conn(self):
                return conn

            _lock = lock
            _read_lock = lock

        db = FakeDB()
        db.set_acl("default", "alice", "automations", True, False)
        row = db.get_acl("default", "alice", "automations")
        assert row is not None
        assert row["can_read"] == 1

        acls = db.list_acls("default")
        assert len(acls) == 1

        db.delete_acl("default", "alice", "automations")
        assert db.get_acl("default", "alice", "automations") is None
