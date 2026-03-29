"""Noba – DB SAML session functions (for SLO support)."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time

logger = logging.getLogger("noba")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS saml_sessions (
            id          TEXT PRIMARY KEY,
            name_id     TEXT NOT NULL,
            username    TEXT NOT NULL,
            session_idx TEXT,
            issued_at   REAL NOT NULL,
            expires_at  REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_saml_session_idx ON saml_sessions (session_idx)")


def store_session(
    conn: sqlite3.Connection, lock: threading.Lock,
    session_id: str, name_id: str, username: str,
    session_idx: str, issued_at: float, expires_at: float,
) -> None:
    try:
        with lock:
            conn.execute(
                "INSERT OR REPLACE INTO saml_sessions "
                "(id, name_id, username, session_idx, issued_at, expires_at) "
                "VALUES (?,?,?,?,?,?)",
                (session_id, name_id, username, session_idx, issued_at, expires_at),
            )
            conn.commit()
    except Exception as e:
        logger.error("store_session failed: %s", e)


def get_session_by_index(
    conn: sqlite3.Connection, lock: threading.Lock, session_idx: str,
) -> dict | None:
    try:
        with lock:
            r = conn.execute(
                "SELECT id, name_id, username, session_idx, issued_at, expires_at "
                "FROM saml_sessions WHERE session_idx = ? AND expires_at > ?",
                (session_idx, time.time()),
            ).fetchone()
        if not r:
            return None
        return {"id": r[0], "name_id": r[1], "username": r[2],
                "session_idx": r[3], "issued_at": r[4], "expires_at": r[5]}
    except Exception as e:
        logger.error("get_session_by_index failed: %s", e)
        return None


def get_session_by_id(
    conn: sqlite3.Connection, lock: threading.Lock, session_id: str,
) -> dict | None:
    try:
        with lock:
            r = conn.execute(
                "SELECT id, name_id, username, session_idx, issued_at, expires_at "
                "FROM saml_sessions WHERE id = ? AND expires_at > ?",
                (session_id, time.time()),
            ).fetchone()
        if not r:
            return None
        return {"id": r[0], "name_id": r[1], "username": r[2],
                "session_idx": r[3], "issued_at": r[4], "expires_at": r[5]}
    except Exception as e:
        logger.error("get_session_by_id failed: %s", e)
        return None


def delete_session_by_index(
    conn: sqlite3.Connection, lock: threading.Lock, session_idx: str,
) -> None:
    try:
        with lock:
            conn.execute("DELETE FROM saml_sessions WHERE session_idx = ?", (session_idx,))
            conn.commit()
    except Exception as e:
        logger.error("delete_session_by_index failed: %s", e)


def prune_expired(conn: sqlite3.Connection, lock: threading.Lock) -> None:
    try:
        with lock:
            conn.execute("DELETE FROM saml_sessions WHERE expires_at < ?", (time.time(),))
            conn.commit()
    except Exception as e:
        logger.error("prune_expired failed: %s", e)


class _SamlMixin:
    """Database mixin — SAML session methods."""

    def saml_store_session(
        self, session_id: str, name_id: str, username: str,
        session_idx: str, issued_at: float, expires_at: float,
    ) -> None:
        self.execute_write(lambda conn: store_session(
            conn, self._lock, session_id, name_id, username, session_idx, issued_at, expires_at,
        ))

    def saml_get_session_by_index(self, session_idx: str) -> dict | None:
        return self.execute_read(lambda conn: get_session_by_index(conn, self._read_lock, session_idx))

    def saml_get_session_by_id(self, session_id: str) -> dict | None:
        return self.execute_read(lambda conn: get_session_by_id(conn, self._read_lock, session_id))

    def saml_delete_session_by_index(self, session_idx: str) -> None:
        self.execute_write(lambda conn: delete_session_by_index(conn, self._lock, session_idx))

    def saml_prune_expired(self) -> None:
        self.execute_write(lambda conn: prune_expired(conn, self._lock))
