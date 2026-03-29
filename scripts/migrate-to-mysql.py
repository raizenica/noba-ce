#!/usr/bin/env python3
"""migrate-to-mysql.py — Copy NOBA data from SQLite to MySQL.

Usage:
    python3 scripts/migrate-to-mysql.py [sqlite_path]

DATABASE_URL must be set in the environment:
    DATABASE_URL=mysql://noba:secret@localhost:3306/noba \\
        python3 scripts/migrate-to-mysql.py ~/.local/share/noba-history.db

The MySQL database must already have the schema initialised.
Run scripts/init-mysql-schema.py first, then run this script.

Notes:
- Skips tables that don't exist in MySQL (uses INSERT IGNORE)
- Preserves all row data; does not truncate existing MySQL rows
- Safe to re-run: duplicate rows are silently skipped
- Requires: pip install PyMySQL
"""
from __future__ import annotations

import os
import re
import signal
import sqlite3
import subprocess
import sys
import time


_PID_FILE = os.environ.get("PID_FILE", "/tmp/noba-web-server.pid")


def _stop_noba() -> bool:
    """Gracefully stop NOBA server. Returns True if server was stopped."""
    pid: int | None = None
    try:
        with open(_PID_FILE) as f:
            pid = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        pass

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
        return False

    for _ in range(20):
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            print("  Server stopped.")
            return True

    try:
        os.kill(pid, signal.SIGKILL)
        print("  Server force-killed.")
    except ProcessLookupError:
        pass
    return True


def _parse_mysql_url(url: str) -> dict:
    """Parse mysql://user:pass@host:port/dbname into a dict for PyMySQL."""
    m = re.match(
        r"mysql(?:\+pymysql)?://([^:@/]+)(?::([^@/]*))?@([^:/]+)(?::(\d+))?/([^?]+)",
        url,
    )
    if not m:
        raise ValueError(f"Cannot parse DATABASE_URL as MySQL URL: {url}")
    user, password, host, port, db = m.groups()
    return {
        "host": host,
        "port": int(port or 3306),
        "user": user,
        "password": password or "",
        "database": db,
        "charset": "utf8mb4",
    }


def main() -> None:
    keep_running = "--keep-running" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url.lower().startswith("mysql"):
        print("ERROR: DATABASE_URL must be set to a MySQL connection string.", file=sys.stderr)
        print("  Example: DATABASE_URL=mysql://user:pass@localhost:3306/noba", file=sys.stderr)
        sys.exit(1)

    sqlite_path = args[0] if args else os.path.expanduser("~/.local/share/noba-history.db")
    if not os.path.exists(sqlite_path):
        print(f"ERROR: SQLite database not found: {sqlite_path}", file=sys.stderr)
        sys.exit(1)

    try:
        import pymysql
    except ImportError:
        print("ERROR: PyMySQL is not installed.", file=sys.stderr)
        print("  pip install PyMySQL", file=sys.stderr)
        sys.exit(1)

    try:
        conn_params = _parse_mysql_url(db_url)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if not keep_running:
        _stop_noba()

    dest_display = f"{conn_params['host']}:{conn_params['port']}/{conn_params['database']}"
    print(f"Source:      {sqlite_path}")
    print(f"Destination: {dest_display}")
    print()

    sq = sqlite3.connect(sqlite_path)
    sq.row_factory = sqlite3.Row
    my = pymysql.connect(**conn_params, autocommit=False)

    # Discover tables in SQLite
    tables = [
        row[0]
        for row in sq.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]

    # Discover tables in MySQL
    with my.cursor() as cur:
        cur.execute("SHOW TABLES")
        my_tables = {row[0] for row in cur.fetchall()}

    total_rows = 0
    for table in sorted(tables):
        if table not in my_tables:
            print(f"  SKIP  {table} (not in MySQL schema)")
            continue

        rows = sq.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
        if not rows:
            print(f"  EMPTY {table}")
            continue

        cols = list(rows[0].keys())
        placeholders = ", ".join(["%s"] * len(cols))
        col_names = ", ".join(f"`{c}`" for c in cols)
        # INSERT IGNORE silently skips duplicate primary-key rows
        sql = f"INSERT IGNORE INTO `{table}` ({col_names}) VALUES ({placeholders})"

        inserted = 0
        errors = 0
        with my.cursor() as cur:
            for row in rows:
                try:
                    cur.execute(sql, tuple(row))
                    if cur.rowcount > 0:
                        inserted += 1
                except Exception as exc:  # noqa: BLE001
                    my.rollback()
                    if errors == 0:
                        print(f"  ERROR {table}: {exc}")
                    errors += 1
                    continue
            my.commit()

        total_rows += inserted
        skipped = len(rows) - inserted - errors
        status = f"{inserted}/{len(rows)} rows inserted"
        if skipped:
            status += f", {skipped} skipped (already exist)"
        if errors:
            status += f", {errors} errors"
        print(f"  OK    {table}: {status}")

    sq.close()
    my.close()
    print()
    print(f"Done. {total_rows} rows migrated across {len(tables)} tables.")
    if not keep_running:
        print()
        print("Next step: restart NOBA with DATABASE_URL pointing to MySQL:")
        print(f"  DATABASE_URL={db_url} noba-web")


if __name__ == "__main__":
    main()
