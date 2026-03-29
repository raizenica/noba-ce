"""Noba – DB SCIM token and provisioning-log functions."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid

logger = logging.getLogger("noba")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scim_tokens (
            id           TEXT PRIMARY KEY,
            token_hash   TEXT NOT NULL UNIQUE,
            created_at   REAL NOT NULL,
            last_used_at REAL,
            expires_at   REAL NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scim_provision_log (
            id        TEXT PRIMARY KEY,
            action    TEXT NOT NULL,
            scim_id   TEXT,
            username  TEXT,
            timestamp REAL NOT NULL,
            result    TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scim_log_ts ON scim_provision_log (timestamp)"
    )


def store_token(
    conn: sqlite3.Connection, lock: threading.Lock,
    token_id: str, token_hash: str,
) -> None:
    try:
        now = time.time()
        expires_at = now + 365 * 86400  # 1 year TTL
        with lock:
            conn.execute("DELETE FROM scim_tokens")  # only one active token
            conn.execute(
                "INSERT INTO scim_tokens (id, token_hash, created_at, expires_at) VALUES (?,?,?,?)",
                (token_id, token_hash, now, expires_at),
            )
            conn.commit()
    except Exception as e:
        logger.error("store_token failed: %s", e)


def verify_token(
    conn: sqlite3.Connection, lock: threading.Lock, token_hash: str,
) -> bool:
    try:
        now = time.time()
        with lock:
            r = conn.execute(
                "SELECT id, expires_at FROM scim_tokens WHERE token_hash = ? AND expires_at > ?",
                (token_hash, now),
            ).fetchone()
            if not r:
                return False
            conn.execute(
                "UPDATE scim_tokens SET last_used_at = ? WHERE id = ?",
                (now, r[0]),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("verify_token failed: %s", e)
        return False


def get_active_token_status(
    conn: sqlite3.Connection, lock: threading.Lock,
) -> dict:
    try:
        now = time.time()
        with lock:
            r = conn.execute(
                "SELECT expires_at, last_used_at FROM scim_tokens WHERE expires_at > ? LIMIT 1",
                (now,),
            ).fetchone()
        if not r:
            return {"active": False, "expires_at": None, "last_used_at": None}
        return {"active": True, "expires_at": r[0], "last_used_at": r[1]}
    except Exception as e:
        logger.error("get_active_token_status failed: %s", e)
        return {"active": False, "expires_at": None, "last_used_at": None}


def log_provision(
    conn: sqlite3.Connection, lock: threading.Lock,
    action: str, scim_id: str | None, username: str | None, result: str,
) -> None:
    try:
        with lock:
            conn.execute(
                "INSERT INTO scim_provision_log (id, action, scim_id, username, timestamp, result) "
                "VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), action, scim_id, username, time.time(), result),
            )
            conn.commit()
    except Exception as e:
        logger.error("log_provision failed: %s", e)


def get_provision_log(
    conn: sqlite3.Connection, lock: threading.Lock, limit: int = 100,
) -> list[dict]:
    try:
        with lock:
            rows = conn.execute(
                "SELECT action, scim_id, username, timestamp, result "
                "FROM scim_provision_log ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{"action": r[0], "scim_id": r[1], "username": r[2],
                 "timestamp": r[3], "result": r[4]} for r in rows]
    except Exception as e:
        logger.error("get_provision_log failed: %s", e)
        return []


class _ScimMixin:
    """Database mixin — SCIM token and provisioning-log methods."""

    def scim_store_token(self, token_id: str, token_hash: str) -> None:
        self.execute_write(lambda conn: store_token(conn, self._lock, token_id, token_hash))

    def scim_verify_token(self, token_hash: str) -> bool:
        return self.execute_write(
            lambda conn: verify_token(conn, self._lock, token_hash)
        )

    def scim_log_provision(
        self, action: str, scim_id: str | None, username: str | None, result: str,
    ) -> None:
        self.execute_write(lambda conn: log_provision(
            conn, self._lock, action, scim_id, username, result,
        ))

    def scim_get_provision_log(self, limit: int = 100) -> list[dict]:
        return self.execute_read(lambda conn: get_provision_log(conn, self._read_lock, limit))

    def scim_get_active_token_status(self) -> dict:
        return self.execute_read(lambda conn: get_active_token_status(conn, self._read_lock))
