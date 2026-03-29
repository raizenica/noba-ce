import pytest
import sqlite3
import threading
import time
from server.db import saml

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    saml.init_schema(c)
    c.commit()
    return c

@pytest.fixture
def lock():
    return threading.Lock()

def test_store_and_get_session(conn, lock):
    saml.store_session(conn, lock, "sess1", "user@corp.com", "alice", "idx1",
                       time.time(), time.time() + 3600)
    row = saml.get_session_by_index(conn, lock, "idx1")
    assert row is not None
    assert row["username"] == "alice"

def test_delete_session(conn, lock):
    saml.store_session(conn, lock, "sess1", "user@corp.com", "alice", "idx1",
                       time.time(), time.time() + 3600)
    saml.delete_session_by_index(conn, lock, "idx1")
    assert saml.get_session_by_index(conn, lock, "idx1") is None

def test_prune_expired(conn, lock):
    saml.store_session(conn, lock, "sess1", "user@corp.com", "alice", "idx1",
                       time.time() - 7200, time.time() - 3600)  # already expired
    saml.prune_expired(conn, lock)
    assert saml.get_session_by_index(conn, lock, "idx1") is None

def test_get_session_by_index_not_found(conn, lock):
    assert saml.get_session_by_index(conn, lock, "nonexistent") is None

def test_prune_preserves_valid_session(conn, lock):
    saml.store_session(conn, lock, "sess1", "user@corp.com", "alice", "idx1",
                       time.time(), time.time() + 3600)  # not expired
    saml.prune_expired(conn, lock)
    assert saml.get_session_by_index(conn, lock, "idx1") is not None

def test_store_session_replace(conn, lock):
    saml.store_session(conn, lock, "sess1", "user@corp.com", "alice", "idx1",
                       time.time(), time.time() + 3600)
    # Replace with same id, different username
    saml.store_session(conn, lock, "sess1", "user2@corp.com", "bob", "idx1",
                       time.time(), time.time() + 7200)
    row = saml.get_session_by_index(conn, lock, "idx1")
    assert row["username"] == "bob"

def test_delete_session_noop(conn, lock):
    """Deleting a non-existent session does not raise."""
    saml.delete_session_by_index(conn, lock, "nonexistent")  # should not raise

def test_two_sessions_independent(conn, lock):
    saml.store_session(conn, lock, "sess1", "u1@corp.com", "alice", "idx1",
                       time.time(), time.time() + 3600)
    saml.store_session(conn, lock, "sess2", "u2@corp.com", "bob", "idx2",
                       time.time(), time.time() + 3600)
    assert saml.get_session_by_index(conn, lock, "idx1")["username"] == "alice"
    assert saml.get_session_by_index(conn, lock, "idx2")["username"] == "bob"

def test_expired_session_not_returned(conn, lock):
    saml.store_session(conn, lock, "sess1", "user@corp.com", "alice", "idx1",
                       time.time() - 7200, time.time() - 3600)  # expired
    assert saml.get_session_by_index(conn, lock, "idx1") is None

def test_get_session_by_id(conn, lock):
    saml.store_session(conn, lock, "sess1", "user@corp.com", "alice", "idx1",
                       time.time(), time.time() + 3600)
    row = saml.get_session_by_id(conn, lock, "sess1")
    assert row is not None
    assert row["username"] == "alice"

def test_get_session_by_id_not_found(conn, lock):
    assert saml.get_session_by_id(conn, lock, "nonexistent") is None
