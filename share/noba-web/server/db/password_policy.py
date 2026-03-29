"""Noba – Password policy: configurable rules + history tracking."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time

logger = logging.getLogger("noba")

DEFAULT_POLICY: dict = {
    "min_length": 8,
    "require_uppercase": True,
    "require_digit": True,
    "require_special": False,
    "max_age_days": 0,
    "history_count": 0,
}


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS password_policies (
            tenant_id         TEXT PRIMARY KEY,
            min_length        INTEGER NOT NULL DEFAULT 8,
            require_uppercase INTEGER NOT NULL DEFAULT 1,
            require_digit     INTEGER NOT NULL DEFAULT 1,
            require_special   INTEGER NOT NULL DEFAULT 0,
            max_age_days      INTEGER NOT NULL DEFAULT 0,
            history_count     INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS password_history (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id      TEXT NOT NULL,
            username       TEXT NOT NULL,
            password_hash  TEXT NOT NULL,
            created_at     INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pw_history_tenant_user
            ON password_history(tenant_id, username);
    """)


_POLICY_COLS = (
    "tenant_id", "min_length", "require_uppercase", "require_digit",
    "require_special", "max_age_days", "history_count",
)


def _row_to_policy(row: sqlite3.Row | tuple | None) -> dict:
    """Convert a DB row to a policy dict with Python booleans."""
    if row is None:
        return dict(DEFAULT_POLICY)
    d = {k: v for k, v in zip(_POLICY_COLS, row)}
    for key in ("require_uppercase", "require_digit", "require_special"):
        d[key] = bool(d.get(key, 0))
    return d


def get_policy(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
) -> dict:
    """Return the password policy for *tenant_id*, or defaults if none set."""
    with lock:
        row = conn.execute(
            "SELECT * FROM password_policies WHERE tenant_id=?",
            (tenant_id,),
        ).fetchone()
    return _row_to_policy(row)


def set_policy(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    **kwargs: int | bool,
) -> None:
    """Upsert password policy for *tenant_id*. Only known keys are accepted."""
    allowed = set(DEFAULT_POLICY.keys())
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    if not filtered:
        return
    # Build the full policy: start from defaults, overlay DB, overlay kwargs
    current = get_policy(conn, lock, tenant_id)
    merged = {**current, **filtered}
    with lock:
        conn.execute(
            "INSERT INTO password_policies"
            " (tenant_id, min_length, require_uppercase, require_digit,"
            "  require_special, max_age_days, history_count)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(tenant_id) DO UPDATE SET"
            "  min_length=excluded.min_length,"
            "  require_uppercase=excluded.require_uppercase,"
            "  require_digit=excluded.require_digit,"
            "  require_special=excluded.require_special,"
            "  max_age_days=excluded.max_age_days,"
            "  history_count=excluded.history_count",
            (
                tenant_id,
                int(merged["min_length"]),
                int(merged["require_uppercase"]),
                int(merged["require_digit"]),
                int(merged["require_special"]),
                int(merged["max_age_days"]),
                int(merged["history_count"]),
            ),
        )
        conn.commit()


def add_password_history(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    username: str,
    password_hash: str,
) -> None:
    """Record a password hash and evict entries beyond *history_count*."""
    now = int(time.time())
    policy = get_policy(conn, lock, tenant_id)
    with lock:
        conn.execute(
            "INSERT INTO password_history (tenant_id, username, password_hash, created_at)"
            " VALUES (?,?,?,?)",
            (tenant_id, username, password_hash, now),
        )
        # Evict old entries if history_count > 0
        hcount = policy["history_count"]
        if hcount > 0:
            conn.execute(
                "DELETE FROM password_history"
                " WHERE tenant_id=? AND username=? AND id NOT IN"
                " (SELECT id FROM password_history"
                "  WHERE tenant_id=? AND username=?"
                "  ORDER BY id DESC LIMIT ?)",
                (tenant_id, username, tenant_id, username, hcount),
            )
        conn.commit()


def check_password_history(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    username: str,
    password_hash: str,
) -> bool:
    """Return True if *password_hash* is in recent history (reuse blocked).

    Returns False immediately if history_count is 0 (disabled).
    """
    policy = get_policy(conn, lock, tenant_id)
    hcount = policy["history_count"]
    if hcount == 0:
        return False
    with lock:
        row = conn.execute(
            "SELECT 1 FROM password_history"
            " WHERE tenant_id=? AND username=? AND password_hash=?"
            " AND id IN"
            " (SELECT id FROM password_history"
            "  WHERE tenant_id=? AND username=?"
            "  ORDER BY id DESC LIMIT ?)",
            (tenant_id, username, password_hash, tenant_id, username, hcount),
        ).fetchone()
    return row is not None


class _PasswordPolicyMixin:
    """Delegation mixin registered on Database in db/core.py."""

    def password_policy_get(self, tenant_id: str) -> dict:
        return get_policy(self._get_read_conn(), self._read_lock, tenant_id)

    def password_policy_set(self, tenant_id: str, **kwargs: int | bool) -> None:
        set_policy(self._get_conn(), self._lock, tenant_id, **kwargs)

    def password_history_add(
        self, tenant_id: str, username: str, password_hash: str,
    ) -> None:
        add_password_history(
            self._get_conn(), self._lock, tenant_id, username, password_hash,
        )

    def password_history_check(
        self, tenant_id: str, username: str, password_hash: str,
    ) -> bool:
        return check_password_history(
            self._get_read_conn(), self._read_lock, tenant_id, username, password_hash,
        )
