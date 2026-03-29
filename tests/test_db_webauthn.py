import pytest
import sqlite3
import threading
from server.db import webauthn as wbn

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    wbn.init_schema(c)
    c.commit()
    return c

@pytest.fixture
def lock():
    return threading.Lock()

def test_store_and_get_credential(conn, lock):
    wbn.store_credential(conn, lock, "u1", b"credid1", b"pubkey1", 0)
    rows = wbn.get_credentials(conn, lock, "u1")
    assert len(rows) == 1
    assert rows[0]["credential_id"] == b"credid1"

def test_update_sign_count(conn, lock):
    wbn.store_credential(conn, lock, "u1", b"credid1", b"pubkey1", 0)
    wbn.update_sign_count(conn, lock, b"credid1", 5)
    rows = wbn.get_credentials(conn, lock, "u1")
    assert rows[0]["sign_count"] == 5

def test_get_credential_by_id(conn, lock):
    wbn.store_credential(conn, lock, "u1", b"credid1", b"pubkey1", 0)
    row = wbn.get_credential_by_id(conn, lock, b"credid1")
    assert row is not None
    assert row["username"] == "u1"

def test_delete_credential(conn, lock):
    wbn.store_credential(conn, lock, "u1", b"credid1", b"pubkey1", 0)
    wbn.delete_credential(conn, lock, b"credid1")
    assert wbn.get_credentials(conn, lock, "u1") == []

def test_backup_codes(conn, lock):
    hashes = ["hash1", "hash2"]
    wbn.store_backup_codes(conn, lock, "u1", hashes)
    assert wbn.verify_backup_code(conn, lock, "u1", "hash1") is True
    assert wbn.verify_backup_code(conn, lock, "u1", "hash1") is False  # consumed
    assert wbn.verify_backup_code(conn, lock, "u1", "hash2") is True

def test_get_credential_by_id_not_found(conn, lock):
    assert wbn.get_credential_by_id(conn, lock, b"nonexistent") is None

def test_backup_codes_replace(conn, lock):
    wbn.store_backup_codes(conn, lock, "u1", ["oldhash"])
    wbn.store_backup_codes(conn, lock, "u1", ["newhash"])
    assert wbn.verify_backup_code(conn, lock, "u1", "oldhash") is False
    assert wbn.verify_backup_code(conn, lock, "u1", "newhash") is True
