"""Tests for db.password_policy: configurable rules + history tracking."""
from __future__ import annotations

import sqlite3
import threading

import pytest

from server.db.password_policy import (
    DEFAULT_POLICY,
    add_password_history,
    check_password_history,
    get_policy,
    init_schema,
    set_policy,
)


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    init_schema(conn)
    return conn, lock


class TestDefaultPolicy:
    def test_returns_defaults_when_no_policy_set(self, db):
        conn, lock = db
        policy = get_policy(conn, lock, "default")
        assert policy == DEFAULT_POLICY

    def test_default_values(self):
        assert DEFAULT_POLICY["min_length"] == 8
        assert DEFAULT_POLICY["require_uppercase"] is True
        assert DEFAULT_POLICY["require_digit"] is True
        assert DEFAULT_POLICY["require_special"] is False
        assert DEFAULT_POLICY["max_age_days"] == 0
        assert DEFAULT_POLICY["history_count"] == 0


class TestSetAndGet:
    def test_set_and_get_policy(self, db):
        conn, lock = db
        set_policy(conn, lock, "t1", min_length=12, require_special=True)
        p = get_policy(conn, lock, "t1")
        assert p["min_length"] == 12
        assert p["require_special"] is True
        # Unchanged fields keep defaults
        assert p["require_uppercase"] is True
        assert p["require_digit"] is True
        assert p["max_age_days"] == 0

    def test_upsert_updates_existing(self, db):
        conn, lock = db
        set_policy(conn, lock, "t1", min_length=10)
        set_policy(conn, lock, "t1", min_length=16)
        assert get_policy(conn, lock, "t1")["min_length"] == 16

    def test_ignores_unknown_keys(self, db):
        conn, lock = db
        set_policy(conn, lock, "t1", bogus_key=999, min_length=14)
        p = get_policy(conn, lock, "t1")
        assert p["min_length"] == 14
        assert "bogus_key" not in p

    def test_no_op_when_no_valid_keys(self, db):
        conn, lock = db
        set_policy(conn, lock, "t1", bogus=1)
        # Should still return defaults (no row inserted)
        assert get_policy(conn, lock, "t1") == DEFAULT_POLICY


class TestTenantIsolation:
    def test_policies_are_per_tenant(self, db):
        conn, lock = db
        set_policy(conn, lock, "t1", min_length=10)
        set_policy(conn, lock, "t2", min_length=20)
        assert get_policy(conn, lock, "t1")["min_length"] == 10
        assert get_policy(conn, lock, "t2")["min_length"] == 20

    def test_history_is_per_tenant(self, db):
        conn, lock = db
        set_policy(conn, lock, "t1", history_count=3)
        set_policy(conn, lock, "t2", history_count=3)
        add_password_history(conn, lock, "t1", "alice", "hash-a")
        add_password_history(conn, lock, "t2", "alice", "hash-b")
        # t1 should see hash-a but not hash-b
        assert check_password_history(conn, lock, "t1", "alice", "hash-a") is True
        assert check_password_history(conn, lock, "t1", "alice", "hash-b") is False


class TestHistoryBlocksReuse:
    def test_recent_hash_is_blocked(self, db):
        conn, lock = db
        set_policy(conn, lock, "default", history_count=3)
        add_password_history(conn, lock, "default", "alice", "hash1")
        add_password_history(conn, lock, "default", "alice", "hash2")
        assert check_password_history(conn, lock, "default", "alice", "hash1") is True
        assert check_password_history(conn, lock, "default", "alice", "hash2") is True

    def test_unknown_hash_not_blocked(self, db):
        conn, lock = db
        set_policy(conn, lock, "default", history_count=3)
        add_password_history(conn, lock, "default", "alice", "hash1")
        assert check_password_history(conn, lock, "default", "alice", "never-used") is False


class TestHistoryRespectsCountLimit:
    def test_evicts_beyond_limit(self, db):
        conn, lock = db
        set_policy(conn, lock, "default", history_count=2)
        add_password_history(conn, lock, "default", "bob", "old")
        add_password_history(conn, lock, "default", "bob", "mid")
        add_password_history(conn, lock, "default", "bob", "new")
        # "old" should have been evicted (only 2 kept)
        assert check_password_history(conn, lock, "default", "bob", "old") is False
        assert check_password_history(conn, lock, "default", "bob", "mid") is True
        assert check_password_history(conn, lock, "default", "bob", "new") is True


class TestZeroHistoryDisablesCheck:
    def test_check_returns_false_when_history_disabled(self, db):
        conn, lock = db
        # Default history_count is 0
        add_password_history(conn, lock, "default", "charlie", "hash1")
        assert check_password_history(conn, lock, "default", "charlie", "hash1") is False

    def test_explicitly_zero_disables(self, db):
        conn, lock = db
        set_policy(conn, lock, "default", history_count=0)
        add_password_history(conn, lock, "default", "charlie", "hash1")
        assert check_password_history(conn, lock, "default", "charlie", "hash1") is False
