"""Noba – Secrets vault: AES-256-GCM encryption + DB CRUD."""
from __future__ import annotations

import base64
import logging
import os
import sqlite3
import threading
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

logger = logging.getLogger("noba")

_PBKDF2_ITERATIONS = 600_000


def derive_key(passphrase: str) -> bytes:
    """Derive a 32-byte AES-256 key from *passphrase* using PBKDF2-HMAC-SHA256.

    The passphrase acts as both password and a fixed salt prefix so that the
    same passphrase always produces the same key (no per-key salt here — the
    per-value randomness lives in the encryption nonce + salt stored with the
    ciphertext).
    """
    salt = b"noba-vault-v1" + passphrase.encode()[:16].ljust(16, b"\x00")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase.encode())


def encrypt_value(key: bytes, plaintext: str) -> str:
    """AES-256-GCM encrypt *plaintext*. Returns base64(nonce[12] + ciphertext+tag)."""
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct_and_tag = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct_and_tag).decode()


def decrypt_value(key: bytes, blob: str) -> str:
    """AES-256-GCM decrypt *blob* produced by encrypt_value. Raises on wrong key/tamper."""
    raw = base64.b64decode(blob)
    nonce, ct_and_tag = raw[:12], raw[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct_and_tag, None).decode()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS vault_secrets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   TEXT NOT NULL DEFAULT 'default',
            name        TEXT NOT NULL,
            encrypted_value TEXT NOT NULL,
            created_at  INTEGER NOT NULL,
            updated_at  INTEGER NOT NULL,
            UNIQUE(tenant_id, name)
        );
        CREATE INDEX IF NOT EXISTS idx_vault_tenant
            ON vault_secrets(tenant_id);
    """)


def store_secret(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    name: str,
    plaintext: str,
    key: bytes,
) -> None:
    """Encrypt *plaintext* and upsert into vault_secrets."""
    encrypted = encrypt_value(key, plaintext)
    now = int(time.time())
    with lock:
        conn.execute(
            "INSERT INTO vault_secrets (tenant_id, name, encrypted_value, created_at, updated_at)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(tenant_id, name)"
            " DO UPDATE SET encrypted_value=excluded.encrypted_value, updated_at=excluded.updated_at",
            (tenant_id, name, encrypted, now, now),
        )
        conn.commit()


def get_secret(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    name: str,
) -> dict | None:
    """Return the raw DB row (including encrypted_value) for a single secret."""
    with lock:
        row = conn.execute(
            "SELECT tenant_id, name, encrypted_value, created_at, updated_at"
            " FROM vault_secrets WHERE tenant_id=? AND name=?",
            (tenant_id, name),
        ).fetchone()
    if not row:
        return None
    return {
        "tenant_id": row[0], "name": row[1], "encrypted_value": row[2],
        "created_at": row[3], "updated_at": row[4],
    }


def list_secrets(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
) -> list[dict]:
    """Return secret names only — never exposes encrypted_value."""
    with lock:
        rows = conn.execute(
            "SELECT tenant_id, name FROM vault_secrets"
            " WHERE tenant_id=? ORDER BY name",
            (tenant_id,),
        ).fetchall()
    return [{"tenant_id": r[0], "name": r[1]} for r in rows]


def delete_secret(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    name: str,
) -> None:
    with lock:
        conn.execute(
            "DELETE FROM vault_secrets WHERE tenant_id=? AND name=?",
            (tenant_id, name),
        )
        conn.commit()


def _get_vault_key() -> bytes:
    """Resolve the vault encryption key.

    Reads ``vaultPassphrase`` from config.yaml. If absent, auto-generates a
    random hex passphrase and persists it back so the key is stable across
    restarts.
    """
    from ..yaml_config import read_yaml_settings, write_yaml_settings
    cfg = read_yaml_settings()
    passphrase = cfg.get("vaultPassphrase", "")
    if not passphrase:
        passphrase = os.urandom(32).hex()
        write_yaml_settings({"vaultPassphrase": passphrase})
        logger.info("vault: auto-generated vaultPassphrase and saved to config")
    return derive_key(passphrase)


class _VaultMixin:
    def vault_store(self, tenant_id: str, name: str, plaintext: str) -> None:
        store_secret(self._get_conn(), self._lock, tenant_id, name, plaintext,
                     _get_vault_key())

    def vault_list(self, tenant_id: str) -> list[dict]:
        return list_secrets(self._get_read_conn(), self._read_lock, tenant_id)

    def vault_get_plaintext(self, tenant_id: str, name: str) -> str | None:
        row = get_secret(self._get_read_conn(), self._read_lock, tenant_id, name)
        if row is None:
            return None
        return decrypt_value(_get_vault_key(), row["encrypted_value"])

    def vault_delete(self, tenant_id: str, name: str) -> None:
        delete_secret(self._get_conn(), self._lock, tenant_id, name)
