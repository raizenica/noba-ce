"""Noba – DB audit functions (log, query, login history, prune)."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time

from ..config import AUDIT_RETENTION_DAYS

logger = logging.getLogger("noba")


def audit_log(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    action: str,
    username: str,
    details: str = "",
    ip: str = "",
    tenant_id: str = "default",
) -> None:
    if len(details) > 512:
        details = details[:512] + "…"
    try:
        with lock:
            conn.execute(
                "INSERT INTO audit (timestamp, username, action, details, ip, tenant_id)"
                " VALUES (?,?,?,?,?,?)",
                (int(time.time()), username, action, details, ip, tenant_id),
            )
            conn.commit()
    except Exception as e:
        logger.error("audit_log failed: %s", e)


def get_audit(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    limit: int = 100,
    offset: int = 0,
    username_filter: str = "",
    action_filter: str = "",
    from_ts: int = 0,
    to_ts: int = 0,
    tenant_id: str = "default",
) -> list[dict]:
    try:
        clauses = ["tenant_id = ?"]
        params: list = [tenant_id]
        if username_filter:
            clauses.append("username = ?")
            params.append(username_filter)
        if action_filter:
            clauses.append("action = ?")
            params.append(action_filter)
        if from_ts:
            clauses.append("timestamp >= ?")
            params.append(from_ts)
        if to_ts:
            clauses.append("timestamp <= ?")
            params.append(to_ts)
        where = " WHERE " + " AND ".join(clauses)
        params.extend([limit, offset])
        with lock:
            rows = conn.execute(
                f"SELECT timestamp, username, action, details, ip FROM audit{where}"
                " ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [
            {"time": r[0], "username": r[1], "action": r[2], "details": r[3], "ip": r[4]}
            for r in rows
        ]
    except Exception as e:
        logger.error("get_audit failed: %s", e)
        return []


def count_audit(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username_filter: str = "",
    action_filter: str = "",
    from_ts: int = 0,
    to_ts: int = 0,
    tenant_id: str = "default",
) -> int:
    try:
        clauses = ["tenant_id = ?"]
        params: list = [tenant_id]
        if username_filter:
            clauses.append("username = ?")
            params.append(username_filter)
        if action_filter:
            clauses.append("action = ?")
            params.append(action_filter)
        if from_ts:
            clauses.append("timestamp >= ?")
            params.append(from_ts)
        if to_ts:
            clauses.append("timestamp <= ?")
            params.append(to_ts)
        where = " WHERE " + " AND ".join(clauses)
        with lock:
            return conn.execute(
                f"SELECT COUNT(*) FROM audit{where}", params
            ).fetchone()[0]
    except Exception as e:
        logger.error("count_audit failed: %s", e)
        return 0


def get_audit_actions(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str = "default",
) -> list[str]:
    """Return distinct action values for filter dropdown."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT DISTINCT action FROM audit WHERE tenant_id = ? ORDER BY action",
                (tenant_id,),
            ).fetchall()
        return [r[0] for r in rows]
    except Exception as e:
        logger.error("get_audit_actions failed: %s", e)
        return []


def get_login_history(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str,
    limit: int = 30,
) -> list[dict]:
    """Get login history for a specific user."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT timestamp, action, details, ip FROM audit "
                "WHERE username = ? AND action IN ('login', 'login_failed') "
                "ORDER BY timestamp DESC LIMIT ?",
                (username, limit),
            ).fetchall()
        return [{"time": r[0], "action": r[1], "details": r[2], "ip": r[3]} for r in rows]
    except Exception as e:
        logger.error("get_login_history failed: %s", e)
        return []


def prune_audit(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    days: int | None = None,
) -> None:
    retention = days if days is not None else AUDIT_RETENTION_DAYS
    cutoff = int(time.time()) - retention * 86400
    try:
        with lock:
            stale = conn.execute(
                "SELECT COUNT(*) FROM audit WHERE timestamp < ?", (cutoff,)
            ).fetchone()[0]
            if stale == 0:
                return
            conn.execute("DELETE FROM audit WHERE timestamp < ?", (cutoff,))
            conn.commit()
            logger.info("Audit pruned: %d rows older than %d days", stale, retention)
    except Exception as e:
        logger.error("prune_audit failed: %s", e)


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS audit (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            username  TEXT NOT NULL,
            action    TEXT NOT NULL,
            details   TEXT,
            ip        TEXT,
            tenant_id TEXT NOT NULL DEFAULT 'default'
        );
        CREATE INDEX IF NOT EXISTS idx_audit_ts
            ON audit(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_user_action
            ON audit(username, action);
    """)
    # Migrate: add tenant_id column if upgrading from pre-enterprise schema
    cols = {row[1] for row in conn.execute("PRAGMA table_info(audit)").fetchall()}
    if "tenant_id" not in cols:
        conn.execute("ALTER TABLE audit ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")
        conn.commit()
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_tenant_ts ON audit(tenant_id, timestamp DESC)"
    )


class _AuditMixin:
    def audit_log(self, action: str, username: str, details: str = "", ip: str = "",
                  tenant_id: str = "default") -> None:
        audit_log(self._get_conn(), self._lock, action, username,
                  details=details, ip=ip, tenant_id=tenant_id)

    def get_audit(self, limit: int = 100, offset: int = 0, username_filter: str = "",
                  action_filter: str = "", from_ts: int = 0, to_ts: int = 0,
                  tenant_id: str = "default") -> list[dict]:
        return get_audit(self._get_read_conn(), self._read_lock, limit=limit, offset=offset,
                         username_filter=username_filter, action_filter=action_filter,
                         from_ts=from_ts, to_ts=to_ts, tenant_id=tenant_id)

    def count_audit(self, username_filter: str = "", action_filter: str = "",
                    from_ts: int = 0, to_ts: int = 0, tenant_id: str = "default") -> int:
        return count_audit(self._get_read_conn(), self._read_lock,
                           username_filter=username_filter, action_filter=action_filter,
                           from_ts=from_ts, to_ts=to_ts, tenant_id=tenant_id)

    def get_audit_actions(self, tenant_id: str = "default") -> list[str]:
        return get_audit_actions(self._get_read_conn(), self._read_lock, tenant_id=tenant_id)

    def get_login_history(self, username: str, limit: int = 30) -> list[dict]:
        return get_login_history(self._get_read_conn(), self._read_lock, username, limit=limit)

    def prune_audit(self, days: int | None = None) -> None:
        prune_audit(self._get_conn(), self._lock, days=days)
