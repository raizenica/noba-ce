"""Noba – DB API key functions."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time

logger = logging.getLogger("noba")


def insert_api_key(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    key_id: str,
    name: str,
    key_hash: str,
    role: str,
    expires_at: int | None = None,
    scope: str = "",
    allowed_ips: str = "[]",
    rate_limit: int = 0,
    tenant_id: str = "default",
) -> None:
    """Insert a new API key."""
    try:
        with lock:
            conn.execute(
                "INSERT INTO api_keys (id, name, key_hash, role, created_at, expires_at, scope, allowed_ips, rate_limit, tenant_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (key_id, name, key_hash, role, int(time.time()), expires_at, scope, allowed_ips, rate_limit, tenant_id),
            )
            conn.commit()
    except Exception as e:
        logger.error("insert_api_key failed: %s", e)


def get_api_key(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    key_hash: str,
) -> dict | None:
    """Look up an API key by its hash and update last_used timestamp."""
    try:
        now = int(time.time())
        with lock:
            r = conn.execute(
                "SELECT id, name, key_hash, role, created_at, expires_at, last_used, scope, allowed_ips, rate_limit "
                "FROM api_keys WHERE key_hash = ? AND (expires_at IS NULL OR expires_at > ?)",
                (key_hash, now),
            ).fetchone()
            if not r:
                return None
            conn.execute(
                "UPDATE api_keys SET last_used = ? WHERE key_hash = ?",
                (int(time.time()), key_hash),
            )
            conn.commit()
        return {
            "id": r[0], "name": r[1], "key_hash": r[2], "role": r[3],
            "created_at": r[4], "expires_at": r[5], "last_used": r[6],
            "scope": r[7] or "", "allowed_ips": r[8] or "[]", "rate_limit": r[9] or 0,
        }
    except Exception as e:
        logger.error("get_api_key failed: %s", e)
        return None


def list_api_keys(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str | None = None,
) -> list[dict]:
    """List all API keys (excluding key_hash from results)."""
    try:
        where = "WHERE tenant_id = ?" if tenant_id is not None else ""
        args = [tenant_id] if tenant_id is not None else []
        with lock:
            rows = conn.execute(
                f"SELECT id, name, role, created_at, expires_at, last_used, scope, allowed_ips, rate_limit "
                f"FROM api_keys {where} ORDER BY created_at DESC",
                args,
            ).fetchall()
        return [
            {
                "id": r[0], "name": r[1], "role": r[2],
                "created_at": r[3], "expires_at": r[4], "last_used": r[5],
                "scope": r[6] or "", "allowed_ips": r[7] or "[]", "rate_limit": r[8] or 0,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("list_api_keys failed: %s", e)
        return []


def delete_api_key(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    key_id: str,
) -> bool:
    """Delete an API key by its id."""
    try:
        with lock:
            cur = conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
            conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_api_key failed: %s", e)
        return False


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            key_hash   TEXT NOT NULL,
            role       TEXT NOT NULL DEFAULT 'viewer',
            created_at INTEGER NOT NULL,
            expires_at INTEGER,
            last_used  INTEGER,
            scope      TEXT NOT NULL DEFAULT '',
            allowed_ips TEXT NOT NULL DEFAULT '[]',
            rate_limit INTEGER NOT NULL DEFAULT 0,
            tenant_id TEXT NOT NULL DEFAULT 'default'
        );
        CREATE INDEX IF NOT EXISTS idx_api_keys_hash
            ON api_keys(key_hash);
    """)


class _ApiKeysMixin:
    def insert_api_key(self, key_id: str, name: str, key_hash: str,
                       role: str, expires_at: int | None = None,
                       scope: str = "", allowed_ips: str = "[]", rate_limit: int = 0,
                       tenant_id: str = "default") -> None:
        insert_api_key(self._get_conn(), self._lock, key_id, name, key_hash,
                       role, expires_at=expires_at, scope=scope,
                       allowed_ips=allowed_ips, rate_limit=rate_limit,
                       tenant_id=tenant_id)

    def get_api_key(self, key_hash: str) -> dict | None:
        # NOTE: get_api_key updates last_used — it's a write operation
        return get_api_key(self._get_conn(), self._lock, key_hash)

    def list_api_keys(self, tenant_id: str | None = None) -> list[dict]:
        return list_api_keys(self._get_read_conn(), self._read_lock, tenant_id=tenant_id)

    def delete_api_key(self, key_id: str) -> bool:
        return delete_api_key(self._get_conn(), self._lock, key_id)
