"""Noba – DB WebAuthn credential and backup-code functions."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid

logger = logging.getLogger("noba")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS webauthn_credentials (
            id            TEXT PRIMARY KEY,
            username      TEXT NOT NULL,
            credential_id BLOB NOT NULL UNIQUE,
            public_key    BLOB NOT NULL,
            sign_count    INTEGER NOT NULL DEFAULT 0,
            name          TEXT NOT NULL DEFAULT '',
            created_at    REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mfa_backup_codes (
            id         TEXT PRIMARY KEY,
            username   TEXT NOT NULL,
            code_hash  TEXT NOT NULL,
            used_at    REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_webauthn_username ON webauthn_credentials (username)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_backup_codes_username ON mfa_backup_codes (username)")


def store_credential(
    conn: sqlite3.Connection, lock: threading.Lock,
    username: str, credential_id: bytes, public_key: bytes,
    sign_count: int, name: str = "",
) -> None:
    try:
        with lock:
            conn.execute(
                "INSERT OR REPLACE INTO webauthn_credentials "
                "(id, username, credential_id, public_key, sign_count, name, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), username, credential_id, public_key, sign_count, name, time.time()),
            )
            conn.commit()
    except Exception as e:
        logger.error("store_credential failed: %s", e)


def get_credentials(
    conn: sqlite3.Connection, lock: threading.Lock, username: str,
) -> list[dict]:
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, username, credential_id, public_key, sign_count, name, created_at "
                "FROM webauthn_credentials WHERE username = ?",
                (username,),
            ).fetchall()
        return [
            {"id": r[0], "username": r[1], "credential_id": r[2],
             "public_key": r[3], "sign_count": r[4], "name": r[5], "created_at": r[6]}
            for r in rows
        ]
    except Exception as e:
        logger.error("get_credentials failed: %s", e)
        return []


def get_credential_by_id(
    conn: sqlite3.Connection, lock: threading.Lock, credential_id: bytes,
) -> dict | None:
    try:
        with lock:
            r = conn.execute(
                "SELECT id, username, credential_id, public_key, sign_count, name, created_at "
                "FROM webauthn_credentials WHERE credential_id = ?",
                (credential_id,),
            ).fetchone()
        if not r:
            return None
        return {"id": r[0], "username": r[1], "credential_id": r[2],
                "public_key": r[3], "sign_count": r[4], "name": r[5], "created_at": r[6]}
    except Exception as e:
        logger.error("get_credential_by_id failed: %s", e)
        return None


def get_all_credentials(
    conn: sqlite3.Connection, lock: threading.Lock,
) -> list[dict]:
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, username, name, created_at, sign_count "
                "FROM webauthn_credentials ORDER BY username, created_at",
            ).fetchall()
        return [
            {"id": r[0], "username": r[1], "name": r[2],
             "created_at": r[3], "sign_count": r[4]}
            for r in rows
        ]
    except Exception as e:
        logger.error("get_all_credentials failed: %s", e)
        return []


def delete_credential_by_uuid(
    conn: sqlite3.Connection, lock: threading.Lock, uid: str,
) -> None:
    try:
        with lock:
            conn.execute("DELETE FROM webauthn_credentials WHERE id = ?", (uid,))
            conn.commit()
    except Exception as e:
        logger.error("delete_credential_by_uuid failed: %s", e)


def update_sign_count(
    conn: sqlite3.Connection, lock: threading.Lock,
    credential_id: bytes, sign_count: int,
) -> None:
    try:
        with lock:
            conn.execute(
                "UPDATE webauthn_credentials SET sign_count = ? WHERE credential_id = ?",
                (sign_count, credential_id),
            )
            conn.commit()
    except Exception as e:
        logger.error("update_sign_count failed: %s", e)


def delete_credential(
    conn: sqlite3.Connection, lock: threading.Lock, credential_id: bytes,
) -> None:
    try:
        with lock:
            conn.execute(
                "DELETE FROM webauthn_credentials WHERE credential_id = ?",
                (credential_id,),
            )
            conn.commit()
    except Exception as e:
        logger.error("delete_credential failed: %s", e)


def store_backup_codes(
    conn: sqlite3.Connection, lock: threading.Lock,
    username: str, code_hashes: list[str],
) -> None:
    """Replace all backup codes for a user."""
    try:
        with lock:
            conn.execute("DELETE FROM mfa_backup_codes WHERE username = ?", (username,))
            for h in code_hashes:
                conn.execute(
                    "INSERT INTO mfa_backup_codes (id, username, code_hash) VALUES (?,?,?)",
                    (str(uuid.uuid4()), username, h),
                )
            conn.commit()
    except Exception as e:
        logger.error("store_backup_codes failed: %s", e)


def verify_backup_code(
    conn: sqlite3.Connection, lock: threading.Lock,
    username: str, code_hash: str,
) -> bool:
    """Check and consume a backup code. Returns True if valid and unused."""
    try:
        with lock:
            r = conn.execute(
                "SELECT id FROM mfa_backup_codes "
                "WHERE username = ? AND code_hash = ? AND used_at IS NULL",
                (username, code_hash),
            ).fetchone()
            if not r:
                return False
            conn.execute(
                "UPDATE mfa_backup_codes SET used_at = ? WHERE id = ?",
                (time.time(), r[0]),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("verify_backup_code failed: %s", e)
        return False


class _WebAuthnMixin:
    """Database mixin — WebAuthn credential and backup-code methods."""

    def webauthn_store_credential(
        self, username: str, credential_id: bytes, public_key: bytes,
        sign_count: int, name: str = "",
    ) -> None:
        self.execute_write(lambda conn: store_credential(
            conn, self._lock, username, credential_id, public_key, sign_count, name,
        ))

    def webauthn_get_credentials(self, username: str) -> list[dict]:
        return self.execute_read(lambda conn: get_credentials(conn, self._read_lock, username))

    def webauthn_get_all_credentials(self) -> list[dict]:
        return self.execute_read(lambda conn: get_all_credentials(conn, self._read_lock))

    def webauthn_delete_credential_by_uuid(self, uid: str) -> None:
        self.execute_write(lambda conn: delete_credential_by_uuid(conn, self._lock, uid))

    def webauthn_get_credential_by_id(self, credential_id: bytes) -> dict | None:
        return self.execute_read(lambda conn: get_credential_by_id(conn, self._read_lock, credential_id))

    def webauthn_update_sign_count(self, credential_id: bytes, sign_count: int) -> None:
        self.execute_write(lambda conn: update_sign_count(conn, self._lock, credential_id, sign_count))

    def webauthn_delete_credential(self, credential_id: bytes) -> None:
        self.execute_write(lambda conn: delete_credential(conn, self._lock, credential_id))

    def webauthn_store_backup_codes(self, username: str, code_hashes: list[str]) -> None:
        self.execute_write(lambda conn: store_backup_codes(conn, self._lock, username, code_hashes))

    def webauthn_verify_backup_code(self, username: str, code_hash: str) -> bool:
        return self.execute_write(
            lambda conn: verify_backup_code(conn, self._lock, username, code_hash)
        )
