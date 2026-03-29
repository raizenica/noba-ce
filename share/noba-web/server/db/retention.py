"""Noba – Configurable data retention policies."""
from __future__ import annotations

import logging
import sqlite3
import threading

logger = logging.getLogger("noba")

DEFAULT_RETENTION = {
    "metrics_days": 30,
    "audit_days": 90,
    "alerts_days": 30,
    "job_runs_days": 30,
}


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS retention_policies (
            tenant_id       TEXT PRIMARY KEY,
            metrics_days    INTEGER NOT NULL DEFAULT 30,
            audit_days      INTEGER NOT NULL DEFAULT 90,
            alerts_days     INTEGER NOT NULL DEFAULT 30,
            job_runs_days   INTEGER NOT NULL DEFAULT 30
        );
    """)


def get_retention(
    conn: sqlite3.Connection, lock: threading.Lock, tenant_id: str,
) -> dict:
    with lock:
        row = conn.execute(
            "SELECT metrics_days, audit_days, alerts_days, job_runs_days"
            " FROM retention_policies WHERE tenant_id=?",
            (tenant_id,),
        ).fetchone()
    if row is None:
        return dict(DEFAULT_RETENTION)
    return {
        "metrics_days": row[0],
        "audit_days": row[1],
        "alerts_days": row[2],
        "job_runs_days": row[3],
    }


def set_retention(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    tenant_id: str,
    metrics_days: int = 30,
    audit_days: int = 90,
    alerts_days: int = 30,
    job_runs_days: int = 30,
) -> None:
    with lock:
        conn.execute(
            "INSERT INTO retention_policies"
            " (tenant_id, metrics_days, audit_days, alerts_days, job_runs_days)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(tenant_id)"
            " DO UPDATE SET metrics_days=excluded.metrics_days,"
            " audit_days=excluded.audit_days,"
            " alerts_days=excluded.alerts_days,"
            " job_runs_days=excluded.job_runs_days",
            (tenant_id, metrics_days, audit_days, alerts_days, job_runs_days),
        )
        conn.commit()


class _RetentionMixin:
    def retention_get(self, tenant_id: str) -> dict:
        return get_retention(self._get_read_conn(), self._read_lock, tenant_id)

    def retention_set(self, tenant_id: str, **kwargs) -> None:
        set_retention(self._get_conn(), self._lock, tenant_id, **kwargs)
