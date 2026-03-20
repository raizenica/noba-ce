"""Noba -- Endpoint monitor CRUD and check-result persistence."""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("noba")


def create_monitor(conn, lock, name: str, url: str, *,
                   method: str = "GET", expected_status: int = 200,
                   check_interval: int = 300, timeout: int = 10,
                   agent_hostname: str | None = None, enabled: bool = True,
                   notify_cert_days: int = 14) -> int | None:
    """Insert a new endpoint monitor and return its id."""
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "INSERT INTO endpoint_monitors "
                "(name, url, method, expected_status, check_interval, timeout, "
                " agent_hostname, enabled, created_at, notify_cert_days) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (name, url, method, expected_status, check_interval, timeout,
                 agent_hostname, 1 if enabled else 0, now, notify_cert_days),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as e:
        logger.error("create_monitor failed: %s", e)
        return None


def get_monitors(conn, lock, *, enabled_only: bool = False) -> list[dict]:
    """Return all endpoint monitors, optionally filtered to enabled ones."""
    try:
        clause = " WHERE enabled = 1" if enabled_only else ""
        with lock:
            rows = conn.execute(
                "SELECT id, name, url, method, expected_status, check_interval, "
                "timeout, agent_hostname, enabled, created_at, last_checked, "
                "last_status, last_response_ms, cert_expiry_days, notify_cert_days "
                f"FROM endpoint_monitors{clause} ORDER BY name"
            ).fetchall()
        return [
            {
                "id": r[0], "name": r[1], "url": r[2], "method": r[3],
                "expected_status": r[4], "check_interval": r[5],
                "timeout": r[6], "agent_hostname": r[7],
                "enabled": bool(r[8]), "created_at": r[9],
                "last_checked": r[10], "last_status": r[11],
                "last_response_ms": r[12], "cert_expiry_days": r[13],
                "notify_cert_days": r[14],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("get_monitors failed: %s", e)
        return []


def get_monitor(conn, lock, monitor_id: int) -> dict | None:
    """Return a single monitor by id."""
    try:
        with lock:
            row = conn.execute(
                "SELECT id, name, url, method, expected_status, check_interval, "
                "timeout, agent_hostname, enabled, created_at, last_checked, "
                "last_status, last_response_ms, cert_expiry_days, notify_cert_days "
                "FROM endpoint_monitors WHERE id = ?",
                (monitor_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "name": row[1], "url": row[2], "method": row[3],
            "expected_status": row[4], "check_interval": row[5],
            "timeout": row[6], "agent_hostname": row[7],
            "enabled": bool(row[8]), "created_at": row[9],
            "last_checked": row[10], "last_status": row[11],
            "last_response_ms": row[12], "cert_expiry_days": row[13],
            "notify_cert_days": row[14],
        }
    except Exception as e:
        logger.error("get_monitor failed: %s", e)
        return None


def update_monitor(conn, lock, monitor_id: int, **kwargs) -> bool:
    """Update fields on an existing monitor."""
    allowed = {
        "name", "url", "method", "expected_status", "check_interval",
        "timeout", "agent_hostname", "enabled", "notify_cert_days",
    }
    sets = []
    vals: list = []
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        if k == "enabled":
            v = 1 if v else 0
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return False
    vals.append(monitor_id)
    try:
        with lock:
            conn.execute(
                f"UPDATE endpoint_monitors SET {', '.join(sets)} WHERE id = ?",
                vals,
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("update_monitor failed: %s", e)
        return False


def delete_monitor(conn, lock, monitor_id: int) -> bool:
    """Delete an endpoint monitor."""
    try:
        with lock:
            cur = conn.execute(
                "DELETE FROM endpoint_monitors WHERE id = ?", (monitor_id,)
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_monitor failed: %s", e)
        return False


def record_check_result(conn, lock, monitor_id: int, *,
                        status: str, response_ms: int | None = None,
                        status_code: int | None = None,
                        cert_expiry_days: int | None = None,
                        error: str | None = None) -> None:
    """Update a monitor with the latest check result."""
    now = int(time.time())
    try:
        with lock:
            conn.execute(
                "UPDATE endpoint_monitors SET last_checked = ?, last_status = ?, "
                "last_response_ms = ?, cert_expiry_days = ? WHERE id = ?",
                (now, status, response_ms, cert_expiry_days, monitor_id),
            )
            conn.commit()
    except Exception as e:
        logger.error("record_check_result failed: %s", e)


def get_due_monitors(conn, lock) -> list[dict]:
    """Return enabled monitors whose next check is due (last_checked + interval < now)."""
    now = int(time.time())
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, name, url, method, expected_status, check_interval, "
                "timeout, agent_hostname, enabled, created_at, last_checked, "
                "last_status, last_response_ms, cert_expiry_days, notify_cert_days "
                "FROM endpoint_monitors "
                "WHERE enabled = 1 AND (last_checked IS NULL OR last_checked + check_interval < ?)",
                (now,),
            ).fetchall()
        return [
            {
                "id": r[0], "name": r[1], "url": r[2], "method": r[3],
                "expected_status": r[4], "check_interval": r[5],
                "timeout": r[6], "agent_hostname": r[7],
                "enabled": bool(r[8]), "created_at": r[9],
                "last_checked": r[10], "last_status": r[11],
                "last_response_ms": r[12], "cert_expiry_days": r[13],
                "notify_cert_days": r[14],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("get_due_monitors failed: %s", e)
        return []
