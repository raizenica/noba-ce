"""Noba – Tenant management DB functions and mixin."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid

logger = logging.getLogger("noba")

_VALID_ROLES = {"admin", "operator", "viewer"}

_DEFAULT_LIMITS: dict = {
    "max_api_keys": 0,
    "max_automations": 0,
    "max_webhooks": 0,
}


def get_tenant_limits(
    conn: sqlite3.Connection, lock: threading.Lock, tenant_id: str
) -> dict:
    """Return quota limits for tenant (0 = unlimited)."""
    with lock:
        row = conn.execute(
            "SELECT limits_json FROM tenants WHERE id = ?", (tenant_id,)
        ).fetchone()
    if row is None:
        return dict(_DEFAULT_LIMITS)
    try:
        parsed = json.loads(row[0] or "{}")
    except (ValueError, TypeError):
        parsed = {}
    return {**_DEFAULT_LIMITS, **parsed}


def set_tenant_limits(
    conn: sqlite3.Connection, lock: threading.Lock, tenant_id: str, limits: dict
) -> None:
    """Persist quota limits for tenant."""
    # Only allow known keys; strip unknown
    clean = {k: max(0, int(v)) for k, v in limits.items() if k in _DEFAULT_LIMITS}
    with lock:
        conn.execute(
            "UPDATE tenants SET limits_json = ? WHERE id = ?",
            (json.dumps(clean), tenant_id),
        )
        conn.commit()


def count_tenant_resources(
    conn: sqlite3.Connection, lock: threading.Lock, tenant_id: str
) -> dict:
    """Return current resource counts for quota display."""
    with lock:
        api_keys = conn.execute(
            "SELECT COUNT(*) FROM api_keys WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()[0]
        automations = conn.execute(
            "SELECT COUNT(*) FROM automations WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()[0]
        # webhooks don't have tenant_id yet — count all as best-effort
        try:
            webhooks = conn.execute("SELECT COUNT(*) FROM webhook_endpoints").fetchone()[0]
        except Exception:
            webhooks = 0
    return {"api_keys": api_keys, "automations": automations, "webhooks": webhooks}


# ── Module-level functions (receive conn + lock) ──────────────────────────────

def create_tenant(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    name: str,
    slug: str,
    metadata: dict | None = None,
) -> dict:
    tenant_id = str(uuid.uuid4())
    now = int(time.time())
    meta = json.dumps(metadata or {})
    with lock:
        conn.execute(
            "INSERT INTO tenants (id, name, slug, created_at, metadata) VALUES (?,?,?,?,?)",
            (tenant_id, name, slug, now, meta),
        )
        conn.commit()
    return {"id": tenant_id, "name": name, "slug": slug,
            "created_at": now, "disabled": 0, "metadata": metadata or {}}


def list_tenants(conn: sqlite3.Connection, lock: threading.Lock) -> list[dict]:
    with lock:
        cur = conn.execute(
            "SELECT id, name, slug, created_at, disabled, metadata FROM tenants ORDER BY name"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_tenant(
    conn: sqlite3.Connection, lock: threading.Lock, tenant_id: str
) -> dict | None:
    with lock:
        cur = conn.execute(
            "SELECT id, name, slug, created_at, disabled, metadata FROM tenants WHERE id = ?",
            (tenant_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(zip([d[0] for d in cur.description], row))


def update_tenant(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    *,
    name: str | None = None,
    disabled: bool | None = None,
    metadata: dict | None = None,
) -> None:
    parts: list[str] = []
    args: list = []
    if name is not None:
        parts.append("name = ?")
        args.append(name)
    if disabled is not None:
        parts.append("disabled = ?")
        args.append(1 if disabled else 0)
    if metadata is not None:
        parts.append("metadata = ?")
        args.append(json.dumps(metadata))
    if not parts:
        return
    args.append(tenant_id)
    with lock:
        conn.execute(f"UPDATE tenants SET {', '.join(parts)} WHERE id = ?", args)
        conn.commit()


def delete_tenant(
    conn: sqlite3.Connection, lock: threading.Lock, tenant_id: str
) -> None:
    with lock:
        conn.execute("DELETE FROM tenant_members WHERE tenant_id = ?", (tenant_id,))
        conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
        conn.commit()


# ── Membership functions ──────────────────────────────────────────────────────

def add_tenant_member(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    username: str,
    role: str = "viewer",
) -> None:
    if role not in _VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of {sorted(_VALID_ROLES)}")
    now = int(time.time())
    with lock:
        conn.execute(
            "INSERT OR REPLACE INTO tenant_members (tenant_id, username, role, joined_at)"
            " VALUES (?,?,?,?)",
            (tenant_id, username, role, now),
        )
        conn.commit()


def remove_tenant_member(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    username: str,
) -> None:
    with lock:
        conn.execute(
            "DELETE FROM tenant_members WHERE tenant_id = ? AND username = ?",
            (tenant_id, username),
        )
        conn.commit()


def update_member_role(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    username: str,
    role: str,
) -> None:
    if role not in _VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'")
    with lock:
        conn.execute(
            "UPDATE tenant_members SET role = ? WHERE tenant_id = ? AND username = ?",
            (role, tenant_id, username),
        )
        conn.commit()


def list_tenant_members(
    conn: sqlite3.Connection, lock: threading.Lock, tenant_id: str
) -> list[dict]:
    with lock:
        cur = conn.execute(
            "SELECT username, role, joined_at FROM tenant_members"
            " WHERE tenant_id = ? ORDER BY username",
            (tenant_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_user_tenant(
    conn: sqlite3.Connection, lock: threading.Lock, username: str
) -> str | None:
    """Return the first tenant_id the user belongs to (alphabetical by tenant_id)."""
    with lock:
        cur = conn.execute(
            "SELECT tenant_id FROM tenant_members WHERE username = ? ORDER BY tenant_id LIMIT 1",
            (username,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_user_tenants(
    conn: sqlite3.Connection, lock: threading.Lock, username: str
) -> list[dict]:
    """Return all tenants the user belongs to with their roles."""
    with lock:
        cur = conn.execute(
            """SELECT t.id, t.name, t.slug, tm.role
               FROM tenants t
               JOIN tenant_members tm ON t.id = tm.tenant_id
               WHERE tm.username = ? AND t.disabled = 0
               ORDER BY t.name""",
            (username,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def count_tenant_members(
    conn: sqlite3.Connection, lock: threading.Lock, tenant_id: str
) -> int:
    with lock:
        cur = conn.execute(
            "SELECT COUNT(*) FROM tenant_members WHERE tenant_id = ?", (tenant_id,)
        )
        return cur.fetchone()[0]


# ── Mixin ─────────────────────────────────────────────────────────────────────

class _TenantsMixin:
    """Mixin providing tenant CRUD and membership management."""

    # ── Tenants ───────────────────────────────────────────────────────────────

    def create_tenant(self, name: str, slug: str, metadata: dict | None = None) -> dict:
        return create_tenant(self._get_conn(), self._lock, name, slug, metadata)

    def list_tenants(self) -> list[dict]:
        return list_tenants(self._get_read_conn(), self._read_lock)

    def get_tenant(self, tenant_id: str) -> dict | None:
        return get_tenant(self._get_read_conn(), self._read_lock, tenant_id)

    def tenant_exists(self, tenant_id: str) -> bool:
        return self.get_tenant(tenant_id) is not None

    def update_tenant(
        self,
        tenant_id: str,
        *,
        name: str | None = None,
        disabled: bool | None = None,
        metadata: dict | None = None,
    ) -> None:
        update_tenant(self._get_conn(), self._lock, tenant_id,
                      name=name, disabled=disabled, metadata=metadata)

    def delete_tenant(self, tenant_id: str) -> None:
        delete_tenant(self._get_conn(), self._lock, tenant_id)

    # ── Members ───────────────────────────────────────────────────────────────

    def add_tenant_member(self, tenant_id: str, username: str, role: str = "viewer") -> None:
        add_tenant_member(self._get_conn(), self._lock, tenant_id, username, role)

    def remove_tenant_member(self, tenant_id: str, username: str) -> None:
        remove_tenant_member(self._get_conn(), self._lock, tenant_id, username)

    def update_tenant_member_role(self, tenant_id: str, username: str, role: str) -> None:
        update_member_role(self._get_conn(), self._lock, tenant_id, username, role)

    def list_tenant_members(self, tenant_id: str) -> list[dict]:
        return list_tenant_members(self._get_read_conn(), self._read_lock, tenant_id)

    def get_user_tenant(self, username: str) -> str | None:
        return get_user_tenant(self._get_read_conn(), self._read_lock, username)

    def get_user_tenants(self, username: str) -> list[dict]:
        return get_user_tenants(self._get_read_conn(), self._read_lock, username)

    def count_tenant_members(self, tenant_id: str) -> int:
        return count_tenant_members(self._get_read_conn(), self._read_lock, tenant_id)

    # ── Quotas ────────────────────────────────────────────────────────────────

    def get_tenant_limits(self, tenant_id: str) -> dict:
        return get_tenant_limits(self._get_read_conn(), self._read_lock, tenant_id)

    def set_tenant_limits(self, tenant_id: str, limits: dict) -> None:
        set_tenant_limits(self._get_conn(), self._lock, tenant_id, limits)

    def count_tenant_resources(self, tenant_id: str) -> dict:
        return count_tenant_resources(self._get_read_conn(), self._read_lock, tenant_id)
