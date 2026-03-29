#!/usr/bin/env python3
"""migrate-to-postgres.py — Copy NOBA data from SQLite to PostgreSQL.

Usage:
    python3 scripts/migrate-to-postgres.py [sqlite_path]

DATABASE_URL must be set in the environment:
    DATABASE_URL=postgresql://noba:secret@localhost:5432/noba \\
        python3 scripts/migrate-to-postgres.py ~/.local/share/noba-history.db

The PostgreSQL database must already have the schema initialised
(start NOBA once with DATABASE_URL set, then run this script).

Notes:
- Automatically stops a running NOBA server before migrating (pass --keep-running to skip)
- Skips tables that don't exist in PostgreSQL (uses INSERT ... ON CONFLICT DO NOTHING)
- Preserves all row data; does not truncate existing PostgreSQL rows
- Safe to re-run: duplicate rows are silently skipped
"""
from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time


_PID_FILE = os.environ.get("PID_FILE", "/tmp/noba-web-server.pid")


def _stop_noba() -> bool:
    """Gracefully stop NOBA server. Returns True if server was stopped."""
    pid: int | None = None

    # Try PID file first
    try:
        with open(_PID_FILE) as f:
            pid = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        pass

    # Fall back to pgrep for uvicorn running server/app
    if pid is None:
        try:
            result = subprocess.run(
                ["pgrep", "-f", "uvicorn.*server.app"],
                capture_output=True, text=True,
            )
            pids = [int(p) for p in result.stdout.split() if p.strip()]
            pid = pids[0] if pids else None
        except Exception:
            pass

    if pid is None:
        return False

    print(f"Stopping NOBA server (PID {pid}) ...")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False  # Already gone

    # Wait up to 10 seconds for clean shutdown
    for _ in range(20):
        time.sleep(0.5)
        try:
            os.kill(pid, 0)  # Check if process still exists
        except ProcessLookupError:
            print("  Server stopped.")
            return True

    # Force kill if still running after 10s
    try:
        os.kill(pid, signal.SIGKILL)
        print("  Server force-killed.")
    except ProcessLookupError:
        pass
    return True


def main() -> None:
    keep_running = "--keep-running" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url.lower().startswith("postgres"):
        print("ERROR: DATABASE_URL must be set to a PostgreSQL connection string.", file=sys.stderr)
        print("  Example: DATABASE_URL=postgresql://user:pass@localhost/noba", file=sys.stderr)
        sys.exit(1)

    sqlite_path = args[0] if args else os.path.expanduser("~/.local/share/noba-history.db")
    if not os.path.exists(sqlite_path):
        print(f"ERROR: SQLite database not found: {sqlite_path}", file=sys.stderr)
        sys.exit(1)

    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2-binary is not installed.", file=sys.stderr)
        print("  pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    if not keep_running:
        _stop_noba()

    print(f"Source:      {sqlite_path}")
    print(f"Destination: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    print()

    sq = sqlite3.connect(sqlite_path)
    sq.row_factory = sqlite3.Row
    pg = psycopg2.connect(db_url)
    pg.autocommit = False
    # Ensure UTF-8 so Unicode characters in text columns (em dash, etc.) transfer cleanly
    pg.set_client_encoding("UTF8")

    # Discover tables in SQLite
    tables = [
        row[0]
        for row in sq.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]

    # Discover tables in PostgreSQL
    with pg.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        pg_tables = {row[0] for row in cur.fetchall()}

    total_rows = 0
    for table in sorted(tables):
        if table not in pg_tables:
            print(f"  SKIP  {table} (not in PostgreSQL schema)")
            continue

        rows = sq.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
        if not rows:
            print(f"  EMPTY {table}")
            continue

        cols = list(rows[0].keys())
        placeholders = ", ".join(["%s"] * len(cols))
        col_names = ", ".join(cols)
        # RETURNING * lets us count actual inserts — rowcount is unreliable for
        # ON CONFLICT DO NOTHING in psycopg2 (returns 0 even on success).
        sql = (
            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) "
            f"ON CONFLICT DO NOTHING RETURNING *"
        )

        inserted = 0
        errors = 0
        with pg.cursor() as cur:
            for row in rows:
                try:
                    cur.execute(sql, tuple(row))
                    if cur.fetchone() is not None:
                        inserted += 1
                except Exception as exc:  # noqa: BLE001
                    pg.rollback()
                    if errors == 0:
                        print(f"  ERROR {table}: {exc}")
                    errors += 1
                    continue
            pg.commit()

        total_rows += inserted
        skipped = len(rows) - inserted - errors
        status = f"{inserted}/{len(rows)} rows inserted"
        if skipped:
            status += f", {skipped} skipped (already exist)"
        if errors:
            status += f", {errors} errors"
        print(f"  OK    {table}: {status}")

    sq.close()
    pg.close()
    print()
    print(f"Done. {total_rows} rows migrated across {len(tables)} tables.")
    if not keep_running:
        print()
        print("Next step: restart NOBA with DATABASE_URL pointing to PostgreSQL:")
        print(f"  DATABASE_URL={db_url} noba-web")


if __name__ == "__main__":
    main()
