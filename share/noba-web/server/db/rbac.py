"""Noba – Resource-type RBAC ACL DB functions."""
from __future__ import annotations

import logging
import sqlite3
import threading

logger = logging.getLogger("noba")

VALID_RESOURCE_TYPES = frozenset({
    "integrations",
    "automations",
    "api_keys",
    "webhooks",
    "users",
    "audit",
})


def init_schema(conn: sqlite3.Connection) -> None:
    """Initialize the resource_acls table."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS resource_acls (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   TEXT NOT NULL DEFAULT 'default',
            username    TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            can_read    INTEGER NOT NULL DEFAULT 1,
            can_write   INTEGER NOT NULL DEFAULT 1,
            UNIQUE(tenant_id, username, resource_type)
        );
        CREATE INDEX IF NOT EXISTS idx_acls_tenant_user
            ON resource_acls(tenant_id, username);
    """
    )


def set_acl(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    username: str,
    resource_type: str,
    can_read: bool,
    can_write: bool,
) -> None:
    """Set or update an ACL for a user on a resource type."""
    if resource_type not in VALID_RESOURCE_TYPES:
        raise ValueError(f"Invalid resource_type: {resource_type!r}")
    with lock:
        conn.execute(
            "INSERT INTO resource_acls (tenant_id, username, resource_type, can_read, can_write)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(tenant_id, username, resource_type)"
            " DO UPDATE SET can_read=excluded.can_read, can_write=excluded.can_write",
            (tenant_id, username, resource_type, int(can_read), int(can_write)),
        )
        conn.commit()


def get_acl(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    username: str,
    resource_type: str,
) -> dict | None:
    """Get an ACL for a user on a resource type."""
    with lock:
        row = conn.execute(
            "SELECT tenant_id, username, resource_type, can_read, can_write"
            " FROM resource_acls WHERE tenant_id=? AND username=? AND resource_type=?",
            (tenant_id, username, resource_type),
        ).fetchone()
    if row is None:
        return None
    return {
        "tenant_id": row[0],
        "username": row[1],
        "resource_type": row[2],
        "can_read": row[3],
        "can_write": row[4],
    }


def list_acls(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    username: str | None = None,
) -> list[dict]:
    """List ACLs for a tenant, optionally filtered by username."""
    with lock:
        if username:
            rows = conn.execute(
                "SELECT tenant_id, username, resource_type, can_read, can_write"
                " FROM resource_acls WHERE tenant_id=? AND username=? ORDER BY resource_type",
                (tenant_id, username),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT tenant_id, username, resource_type, can_read, can_write"
                " FROM resource_acls WHERE tenant_id=? ORDER BY username, resource_type",
                (tenant_id,),
            ).fetchall()
    return [
        {
            "tenant_id": r[0],
            "username": r[1],
            "resource_type": r[2],
            "can_read": r[3],
            "can_write": r[4],
        }
        for r in rows
    ]


def delete_acl(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    username: str,
    resource_type: str,
) -> None:
    """Delete an ACL for a user on a resource type."""
    with lock:
        conn.execute(
            "DELETE FROM resource_acls WHERE tenant_id=? AND username=? AND resource_type=?",
            (tenant_id, username, resource_type),
        )
        conn.commit()


class _RBACMixin:
    """Mixin for DB classes to add RBAC methods."""

    def set_acl(
        self,
        tenant_id: str,
        username: str,
        resource_type: str,
        can_read: bool,
        can_write: bool,
    ) -> None:
        """Set or update an ACL for a user on a resource type."""
        set_acl(
            self._get_conn(),
            self._lock,
            tenant_id,
            username,
            resource_type,
            can_read,
            can_write,
        )

    def get_acl(
        self, tenant_id: str, username: str, resource_type: str
    ) -> dict | None:
        """Get an ACL for a user on a resource type."""
        return get_acl(
            self._get_read_conn(),
            self._read_lock,
            tenant_id,
            username,
            resource_type,
        )

    def list_acls(
        self, tenant_id: str, username: str | None = None
    ) -> list[dict]:
        """List ACLs for a tenant, optionally filtered by username."""
        return list_acls(
            self._get_read_conn(), self._read_lock, tenant_id, username=username
        )

    def delete_acl(
        self, tenant_id: str, username: str, resource_type: str
    ) -> None:
        """Delete an ACL for a user on a resource type."""
        delete_acl(self._get_conn(), self._lock, tenant_id, username, resource_type)
