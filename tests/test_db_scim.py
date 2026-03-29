import pytest
import sqlite3
import threading
from server.db import scim

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    scim.init_schema(c)
    c.commit()
    return c

@pytest.fixture
def lock():
    return threading.Lock()

def test_store_and_verify_token(conn, lock):
    scim.store_token(conn, lock, "tok1", "hash1")
    assert scim.verify_token(conn, lock, "hash1") is True

def test_invalid_token_rejected(conn, lock):
    assert scim.verify_token(conn, lock, "nothash") is False

def test_provision_log(conn, lock):
    scim.log_provision(conn, lock, "create", "ext-123", "alice", "ok")
    logs = scim.get_provision_log(conn, lock, limit=10)
    assert len(logs) == 1
    assert logs[0]["action"] == "create"
    assert logs[0]["username"] == "alice"

def test_token_rotation(conn, lock):
    """Storing a new token invalidates the previous one."""
    scim.store_token(conn, lock, "tok1", "hash1")
    scim.store_token(conn, lock, "tok2", "hash2")
    assert scim.verify_token(conn, lock, "hash1") is False   # old token gone
    assert scim.verify_token(conn, lock, "hash2") is True    # new token works

def test_verify_token_updates_last_used_at(conn, lock):
    scim.store_token(conn, lock, "tok1", "hash1")
    scim.verify_token(conn, lock, "hash1")
    with lock:
        row = conn.execute(
            "SELECT last_used_at FROM scim_tokens WHERE token_hash = ?", ("hash1",)
        ).fetchone()
    assert row is not None
    assert row[0] is not None   # last_used_at was set

def test_provision_log_null_fields(conn, lock):
    scim.log_provision(conn, lock, "delete", None, None, "ok")
    logs = scim.get_provision_log(conn, lock, limit=10)
    assert len(logs) == 1
    assert logs[0]["scim_id"] is None
    assert logs[0]["username"] is None

def test_provision_log_limit(conn, lock):
    for i in range(5):
        scim.log_provision(conn, lock, "update", f"id-{i}", f"user{i}", "ok")
    logs = scim.get_provision_log(conn, lock, limit=2)
    assert len(logs) == 2
