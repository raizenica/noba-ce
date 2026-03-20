"""Noba -- Backup verification persistence."""
from __future__ import annotations

import json
import time


def record_verification(
    conn, lock, backup_path: str, hostname: str,
    verification_type: str, status: str,
    details: str | None = None,
) -> int | None:
    """Record a completed backup verification.

    Returns the row id on success, or None on failure.
    """
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "INSERT INTO backup_verifications "
                "(backup_path, hostname, verification_type, status, details, verified_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (backup_path, hostname, verification_type, status, details, now),
            )
            conn.commit()
            return cur.lastrowid
    except Exception:
        return None


def list_verifications(
    conn, lock,
    hostname: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Return backup verification history, optionally filtered by hostname."""
    clauses: list[str] = []
    params: list = []
    if hostname:
        clauses.append("hostname = ?")
        params.append(hostname)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with lock:
        rows = conn.execute(
            "SELECT id, backup_path, hostname, verification_type, status, "
            "details, verified_at "
            f"FROM backup_verifications{where} "
            "ORDER BY verified_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
    return [
        {
            "id": r[0],
            "backup_path": r[1],
            "hostname": r[2],
            "verification_type": r[3],
            "status": r[4],
            "details": json.loads(r[5]) if r[5] else None,
            "verified_at": r[6],
        }
        for r in rows
    ]


def get_321_status(conn, lock) -> list[dict]:
    """Return 3-2-1 compliance status for all tracked backups."""
    with lock:
        rows = conn.execute(
            "SELECT id, backup_name, copies, media_types, has_offsite, "
            "last_verified, updated_at "
            "FROM backup_321_status ORDER BY backup_name"
        ).fetchall()
    return [
        {
            "id": r[0],
            "backup_name": r[1],
            "copies": r[2],
            "media_types": json.loads(r[3]) if r[3] else [],
            "has_offsite": bool(r[4]),
            "last_verified": r[5],
            "updated_at": r[6],
        }
        for r in rows
    ]


def update_321_status(
    conn, lock, backup_name: str, *,
    copies: int | None = None,
    media_types: list[str] | None = None,
    has_offsite: bool | None = None,
    last_verified: int | None = None,
) -> int | None:
    """Insert or update 3-2-1 compliance tracking for a backup.

    Uses INSERT OR REPLACE keyed on backup_name. Returns the row id.
    """
    now = int(time.time())
    try:
        with lock:
            # Read existing row if any
            existing = conn.execute(
                "SELECT copies, media_types, has_offsite, last_verified "
                "FROM backup_321_status WHERE backup_name = ?",
                (backup_name,),
            ).fetchone()

            if existing:
                cur_copies = copies if copies is not None else existing[0]
                cur_media = (json.dumps(media_types) if media_types is not None
                             else existing[1])
                cur_offsite = (int(has_offsite) if has_offsite is not None
                               else existing[2])
                cur_verified = (last_verified if last_verified is not None
                                else existing[3])
                conn.execute(
                    "UPDATE backup_321_status SET copies=?, media_types=?, "
                    "has_offsite=?, last_verified=?, updated_at=? "
                    "WHERE backup_name=?",
                    (cur_copies, cur_media, cur_offsite, cur_verified,
                     now, backup_name),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT id FROM backup_321_status WHERE backup_name=?",
                    (backup_name,),
                ).fetchone()
                return row[0] if row else None
            else:
                cur = conn.execute(
                    "INSERT INTO backup_321_status "
                    "(backup_name, copies, media_types, has_offsite, "
                    "last_verified, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        backup_name,
                        copies or 0,
                        json.dumps(media_types or []),
                        int(has_offsite) if has_offsite is not None else 0,
                        last_verified,
                        now,
                    ),
                )
                conn.commit()
                return cur.lastrowid
    except Exception:
        return None
