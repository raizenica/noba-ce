"""Noba – DB token persistence functions (refresh tokens)."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time

logger = logging.getLogger("noba")


def _insert_token(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    token_hash: str,
    username: str,
    role: str,
    created_at: int,
    expires_at: int,
) -> None:
    """Persist a hashed token to the DB."""
    try:
        with lock:
            conn.execute(
                "INSERT OR REPLACE INTO tokens "
                "(token_hash, username, role, created_at, expires_at) "
                "VALUES (?,?,?,?,?)",
                (token_hash, username, role, created_at, expires_at),
            )
            conn.commit()
    except Exception as e:
        logger.error("_insert_token failed: %s", e)


def _delete_token(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    token_hash: str,
) -> None:
    """Delete a hashed token from the DB."""
    try:
        with lock:
            conn.execute("DELETE FROM tokens WHERE token_hash = ?", (token_hash,))
            conn.commit()
    except Exception as e:
        logger.error("_delete_token failed: %s", e)


def _get_token(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    token_hash: str,
) -> dict | None:
    """Look up a hashed token. Returns row dict or None if not found / expired."""
    try:
        now = int(time.time())
        with lock:
            cur = conn.execute(
                "SELECT username, role, expires_at FROM tokens "
                "WHERE token_hash = ? AND expires_at > ?",
                (token_hash, now),
            )
            row = cur.fetchone()
        if row:
            return {"username": row[0], "role": row[1], "expires_at": row[2]}
    except Exception as e:
        logger.error("_get_token failed: %s", e)
    return None


def _cleanup_tokens(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> None:
    """Remove all expired tokens from the DB."""
    try:
        now = int(time.time())
        with lock:
            conn.execute("DELETE FROM tokens WHERE expires_at <= ?", (now,))
            conn.commit()
    except Exception as e:
        logger.error("_cleanup_tokens failed: %s", e)


def _load_tokens(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> list[dict]:
    """Return all non-expired tokens from the DB for in-memory hydration."""
    try:
        now = int(time.time())
        with lock:
            cur = conn.execute(
                "SELECT token_hash, username, role, expires_at FROM tokens WHERE expires_at > ?",
                (now,),
            )
            rows = cur.fetchall()
        return [
            {"token_hash": r[0], "username": r[1], "role": r[2], "expires_at": r[3]}
            for r in rows
        ]
    except Exception as e:
        logger.error("_load_tokens failed: %s", e)
        return []
