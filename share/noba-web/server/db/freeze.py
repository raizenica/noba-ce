"""Noba – Change freeze window DB functions."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid

logger = logging.getLogger("noba")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS freeze_windows (
            id          TEXT PRIMARY KEY,
            tenant_id   TEXT NOT NULL DEFAULT 'default',
            name        TEXT NOT NULL,
            start_ts    INTEGER NOT NULL,
            end_ts      INTEGER NOT NULL,
            created_by  TEXT NOT NULL,
            created_at  INTEGER NOT NULL,
            reason      TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_freeze_tenant_ts
            ON freeze_windows(tenant_id, start_ts, end_ts);
    """)


def add_window(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    name: str,
    start_ts: int,
    end_ts: int,
    created_by: str,
    reason: str = "",
) -> str:
    """Insert a freeze window, return its id."""
    window_id = str(uuid.uuid4())
    with lock:
        conn.execute(
            "INSERT INTO freeze_windows (id, tenant_id, name, start_ts, end_ts,"
            " created_by, created_at, reason) VALUES (?,?,?,?,?,?,?,?)",
            (window_id, tenant_id, name, start_ts, end_ts,
             created_by, int(time.time()), reason),
        )
        conn.commit()
    return window_id


def list_windows(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
) -> list[dict]:
    with lock:
        rows = conn.execute(
            "SELECT id, tenant_id, name, start_ts, end_ts, created_by, created_at, reason"
            " FROM freeze_windows WHERE tenant_id=? ORDER BY start_ts DESC",
            (tenant_id,),
        ).fetchall()
    return [
        {"id": r[0], "tenant_id": r[1], "name": r[2], "start_ts": r[3],
         "end_ts": r[4], "created_by": r[5], "created_at": r[6], "reason": r[7]}
        for r in rows
    ]


def delete_window(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    window_id: str,
) -> None:
    with lock:
        conn.execute("DELETE FROM freeze_windows WHERE id=?", (window_id,))
        conn.commit()


def is_frozen(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
) -> bool:
    """Return True if the current time falls within any active freeze window."""
    now = int(time.time())
    with lock:
        row = conn.execute(
            "SELECT 1 FROM freeze_windows"
            " WHERE tenant_id=? AND start_ts <= ? AND end_ts >= ? LIMIT 1",
            (tenant_id, now, now),
        ).fetchone()
    return row is not None


class _FreezeMixin:
    def add_freeze_window(self, tenant_id: str, name: str, start_ts: int,
                          end_ts: int, created_by: str, reason: str = "") -> str:
        from .freeze import add_window
        return add_window(self._get_conn(), self._lock, tenant_id, name,
                          start_ts, end_ts, created_by, reason)

    def list_freeze_windows(self, tenant_id: str) -> list[dict]:
        from .freeze import list_windows
        return list_windows(self._get_read_conn(), self._read_lock, tenant_id)

    def delete_freeze_window(self, window_id: str) -> None:
        from .freeze import delete_window
        delete_window(self._get_conn(), self._lock, window_id)

    def is_frozen(self, tenant_id: str) -> bool:
        from .freeze import is_frozen
        return is_frozen(self._get_read_conn(), self._read_lock, tenant_id)
