"""Noba – DB notification functions."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time

logger = logging.getLogger("noba")


def insert_notification(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    level: str,
    title: str,
    message: str,
    username: str | None = None,
) -> None:
    """Insert a notification."""
    try:
        with lock:
            conn.execute(
                "INSERT INTO notifications (timestamp, level, title, message, username) "
                "VALUES (?,?,?,?,?)",
                (int(time.time()), level, title, message, username),
            )
            conn.commit()
    except Exception as e:
        logger.error("insert_notification failed: %s", e)


def get_notifications(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str | None = None,
    unread_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    """Query notifications with optional filters."""
    try:
        clauses: list[str] = []
        params: list = []
        if username:
            clauses.append("(username = ? OR username IS NULL)")
            params.append(username)
        if unread_only:
            clauses.append("read = 0")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with lock:
            rows = conn.execute(
                "SELECT id, timestamp, level, title, message, read, username "
                f"FROM notifications{where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
        return [
            {
                "id": r[0], "timestamp": r[1], "level": r[2],
                "title": r[3], "message": r[4], "read": bool(r[5]),
                "username": r[6],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("get_notifications failed: %s", e)
        return []


def mark_notification_read(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    notif_id: int,
    username: str,
) -> None:
    """Mark a single notification as read."""
    try:
        with lock:
            conn.execute(
                "UPDATE notifications SET read = 1 "
                "WHERE id = ? AND (username = ? OR username IS NULL)",
                (notif_id, username),
            )
            conn.commit()
    except Exception as e:
        logger.error("mark_notification_read failed: %s", e)


def mark_all_notifications_read(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str,
) -> None:
    """Mark all notifications for a user as read."""
    try:
        with lock:
            conn.execute(
                "UPDATE notifications SET read = 1 "
                "WHERE (username = ? OR username IS NULL) AND read = 0",
                (username,),
            )
            conn.commit()
    except Exception as e:
        logger.error("mark_all_notifications_read failed: %s", e)


def get_unread_count(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str,
) -> int:
    """Return count of unread notifications for a user."""
    try:
        with lock:
            r = conn.execute(
                "SELECT COUNT(*) FROM notifications "
                "WHERE (username = ? OR username IS NULL) AND read = 0",
                (username,),
            ).fetchone()
        return r[0] if r else 0
    except Exception as e:
        logger.error("get_unread_count failed: %s", e)
        return 0
