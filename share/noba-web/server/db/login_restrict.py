"""Noba – Login IP allowlist: tenant-scoped CIDR rules."""
from __future__ import annotations

import ipaddress
import logging
import sqlite3
import threading

logger = logging.getLogger("noba")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS login_ip_allowlists (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   TEXT NOT NULL DEFAULT 'default',
            cidr        TEXT NOT NULL,
            label       TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_login_ip_tenant
            ON login_ip_allowlists(tenant_id);
    """)


def add_allowed_cidr(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    cidr: str,
    label: str = "",
) -> int:
    """Insert a CIDR rule after validation, return lastrowid."""
    # Validate — raises ValueError on bad input
    ipaddress.ip_network(cidr, strict=False)
    with lock:
        cur = conn.execute(
            "INSERT INTO login_ip_allowlists (tenant_id, cidr, label)"
            " VALUES (?,?,?)",
            (tenant_id, cidr, label),
        )
        conn.commit()
        return cur.lastrowid


def list_allowed_cidrs(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
) -> list[dict]:
    with lock:
        rows = conn.execute(
            "SELECT id, tenant_id, cidr, label"
            " FROM login_ip_allowlists WHERE tenant_id=? ORDER BY id",
            (tenant_id,),
        ).fetchall()
    return [{"id": r[0], "tenant_id": r[1], "cidr": r[2], "label": r[3]} for r in rows]


def delete_allowed_cidr(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    rule_id: int,
) -> None:
    with lock:
        conn.execute("DELETE FROM login_ip_allowlists WHERE id=?", (rule_id,))
        conn.commit()


def is_ip_allowed(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    ip_str: str,
) -> bool:
    """Check if *ip_str* is permitted for *tenant_id*.

    If the tenant has NO rules, all IPs are allowed (open by default).
    If rules exist, the IP must match at least one CIDR.
    """
    with lock:
        rows = conn.execute(
            "SELECT cidr FROM login_ip_allowlists WHERE tenant_id=?",
            (tenant_id,),
        ).fetchall()
    if not rows:
        return True  # No rules → open by default
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    for row in rows:
        net = ipaddress.ip_network(row["cidr"], strict=False)
        if addr in net:
            return True
    return False


class _LoginRestrictMixin:
    """Delegation mixin registered on Database in db/core.py."""

    def add_login_cidr(self, tenant_id: str, cidr: str, label: str = "") -> int:
        return add_allowed_cidr(
            self._get_conn(), self._lock, tenant_id, cidr, label,
        )

    def list_login_cidrs(self, tenant_id: str) -> list[dict]:
        return list_allowed_cidrs(
            self._get_read_conn(), self._read_lock, tenant_id,
        )

    def delete_login_cidr(self, rule_id: int) -> None:
        delete_allowed_cidr(self._get_conn(), self._lock, rule_id)

    def is_login_ip_allowed(self, tenant_id: str, ip: str) -> bool:
        return is_ip_allowed(
            self._get_read_conn(), self._read_lock, tenant_id, ip,
        )
