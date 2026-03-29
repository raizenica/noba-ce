from __future__ import annotations
import pytest
from server.db.core import Database

@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    yield d
    d._conn.close()

def test_scim_active_token_status_no_token(db):
    status = db.scim_get_active_token_status()
    assert status == {"active": False, "expires_at": None, "last_used_at": None}

def test_scim_active_token_status_with_token(db):
    import hashlib
    import uuid
    raw = str(uuid.uuid4())
    h = hashlib.sha256(raw.encode()).hexdigest()
    db.scim_store_token(str(uuid.uuid4()), h)
    status = db.scim_get_active_token_status()
    assert status["active"] is True
    assert status["expires_at"] is not None

def test_webauthn_get_all_credentials_empty(db):
    creds = db.webauthn_get_all_credentials()
    assert creds == []

def test_webauthn_get_all_credentials_returns_rows(db):
    db.webauthn_store_credential("alice", b"cred1", b"pubkey1", 0, "laptop")
    db.webauthn_store_credential("bob",   b"cred2", b"pubkey2", 0, "yubikey")
    creds = db.webauthn_get_all_credentials()
    assert len(creds) == 2
    usernames = {c["username"] for c in creds}
    assert usernames == {"alice", "bob"}

def test_webauthn_delete_credential_by_uuid(db):
    db.webauthn_store_credential("alice", b"cred3", b"pubkey3", 0, "phone")
    creds = db.webauthn_get_all_credentials()
    assert len(creds) == 1
    uid = creds[0]["id"]
    db.webauthn_delete_credential_by_uuid(uid)
    assert db.webauthn_get_all_credentials() == []

def test_webauthn_delete_nonexistent_uuid_noop(db):
    db.webauthn_delete_credential_by_uuid("does-not-exist")  # must not raise
