"""Tests for db.vault: AES-256-GCM encrypt/decrypt and secret CRUD."""
from __future__ import annotations
import sqlite3
import threading
import pytest
from server.db.vault import (
    init_schema, derive_key, encrypt_value, decrypt_value,
    store_secret, get_secret, list_secrets, delete_secret,
)

TEST_PASSPHRASE = "test-passphrase-for-unit-tests"


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    init_schema(conn)
    return conn, lock


class TestEncryption:
    def test_encrypt_decrypt_round_trip(self):
        key = derive_key(TEST_PASSPHRASE)
        ciphertext = encrypt_value(key, "super-secret-value")
        assert decrypt_value(key, ciphertext) == "super-secret-value"

    def test_different_encryptions_of_same_value_differ(self):
        key = derive_key(TEST_PASSPHRASE)
        c1 = encrypt_value(key, "value")
        c2 = encrypt_value(key, "value")
        assert c1 != c2  # random salt + nonce

    def test_wrong_key_raises(self):
        key1 = derive_key("passphrase-1")
        key2 = derive_key("passphrase-2")
        ciphertext = encrypt_value(key1, "secret")
        with pytest.raises(Exception):
            decrypt_value(key2, ciphertext)

    def test_derive_key_is_32_bytes(self):
        key = derive_key(TEST_PASSPHRASE)
        assert len(key) == 32


class TestVaultCRUD:
    def test_store_and_retrieve(self, db):
        conn, lock = db
        key = derive_key(TEST_PASSPHRASE)
        store_secret(conn, lock, "default", "db-password", "s3cr3t", key)
        row = get_secret(conn, lock, "default", "db-password")
        assert row is not None
        assert decrypt_value(key, row["encrypted_value"]) == "s3cr3t"

    def test_list_shows_names_only(self, db):
        conn, lock = db
        key = derive_key(TEST_PASSPHRASE)
        store_secret(conn, lock, "default", "key-a", "val-a", key)
        store_secret(conn, lock, "default", "key-b", "val-b", key)
        rows = list_secrets(conn, lock, "default")
        assert len(rows) == 2
        assert all("encrypted_value" not in r for r in rows)
        assert {r["name"] for r in rows} == {"key-a", "key-b"}

    def test_tenant_isolation(self, db):
        conn, lock = db
        key = derive_key(TEST_PASSPHRASE)
        store_secret(conn, lock, "t1", "secret", "value-t1", key)
        store_secret(conn, lock, "t2", "secret", "value-t2", key)
        assert list_secrets(conn, lock, "t1") == [{"name": "secret", "tenant_id": "t1"}]

    def test_delete_secret(self, db):
        conn, lock = db
        key = derive_key(TEST_PASSPHRASE)
        store_secret(conn, lock, "default", "temp", "value", key)
        delete_secret(conn, lock, "default", "temp")
        assert get_secret(conn, lock, "default", "temp") is None

    def test_upsert_overwrites(self, db):
        conn, lock = db
        key = derive_key(TEST_PASSPHRASE)
        store_secret(conn, lock, "default", "pw", "old", key)
        store_secret(conn, lock, "default", "pw", "new", key)
        row = get_secret(conn, lock, "default", "pw")
        assert decrypt_value(key, row["encrypted_value"]) == "new"
