#!/usr/bin/env python3
"""init-mysql-schema.py — Create NOBA schema in MySQL/MariaDB from the live SQLite DB.

Reads the table definitions directly from the SQLite source database and
translates them to MySQL-compatible DDL. This guarantees the MySQL schema
always matches the actual SQLite column set, regardless of schema evolution.

Usage:
    DATABASE_URL=mysql://noba:secret@localhost:3306/noba \\
        python3 scripts/init-mysql-schema.py [sqlite_path]

Idempotent: uses CREATE TABLE IF NOT EXISTS throughout.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys


def _parse_mysql_url(url: str) -> dict:
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


def _sqlite_type_to_mysql(col_type: str) -> str:
    """Map SQLite type affinity to a concrete MySQL type."""
    t = col_type.upper().strip()
    if not t or t in ("TEXT", "CLOB"):
        return "MEDIUMTEXT"
    if t in ("INTEGER", "INT"):
        return "BIGINT"
    if t.startswith("INTEGER") or t.startswith("INT"):
        return "BIGINT"
    if t in ("REAL", "DOUBLE", "FLOAT", "NUMERIC", "DECIMAL"):
        return "DOUBLE"
    if t == "BLOB":
        return "BLOB"
    if t == "BOOLEAN":
        return "TINYINT(1)"
    # Fallback: keep as-is (MySQL is lenient)
    return col_type or "MEDIUMTEXT"


# MySQL reserved words that need backtick quoting as column names
_MYSQL_RESERVED = frozenset({
    "condition", "interval", "key", "index", "order", "select", "where",
    "group", "from", "to", "by", "as", "on", "in", "is", "not", "null",
    "and", "or", "set", "status", "trigger", "type", "value", "values",
    "table", "column", "row", "schema", "database", "read", "write",
    "role", "name", "timestamp", "action", "check",
})


def _col_name(name: str) -> str:
    if name.lower() in _MYSQL_RESERVED:
        return f"`{name}`"
    return name


def translate_table(table: str, sq: sqlite3.Connection) -> str | None:
    """Generate CREATE TABLE IF NOT EXISTS DDL for MySQL from SQLite PRAGMA."""
    cols = sq.execute(f"PRAGMA table_info({table})").fetchall()  # noqa: S608
    if not cols:
        return None

    col_defs = []
    pk_cols = [c[1] for c in cols if c[5] > 0]  # c[5] = pk order

    for _, name, col_type, notnull, default, pk in cols:
        mysql_type = _sqlite_type_to_mysql(col_type)

        # Use VARCHAR for known short-text primary key columns
        if pk and mysql_type == "MEDIUMTEXT":
            mysql_type = "VARCHAR(255)"

        parts = [f"{_col_name(name)} {mysql_type}"]

        if pk and len(pk_cols) == 1:
            if "INT" in mysql_type.upper():
                parts = [f"{_col_name(name)} {mysql_type} AUTO_INCREMENT PRIMARY KEY"]
            else:
                parts = [f"{_col_name(name)} {mysql_type} PRIMARY KEY"]
        else:
            if notnull:
                parts.append("NOT NULL")
            if default is not None:
                # Quote string defaults; leave numeric/NULL bare
                if default.upper() == "NULL":
                    parts.append("DEFAULT NULL")
                elif re.match(r"^-?\d+(\.\d+)?$", str(default)):
                    parts.append(f"DEFAULT {default}")
                else:
                    escaped = str(default).replace("'", "''")
                    parts.append(f"DEFAULT '{escaped}'")

        col_defs.append(" ".join(parts))

    if len(pk_cols) > 1:
        pk_list = ", ".join(_col_name(c) for c in pk_cols)
        col_defs.append(f"PRIMARY KEY ({pk_list})")

    cols_sql = ",\n    ".join(col_defs)
    return (
        f"CREATE TABLE IF NOT EXISTS `{table}` (\n"
        f"    {cols_sql}\n"
        f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


def main() -> None:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url.lower().startswith("mysql"):
        print("ERROR: DATABASE_URL must be a MySQL connection string.", file=sys.stderr)
        sys.exit(1)

    sqlite_path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
        "~/.local/share/noba-history.db"
    )
    if not os.path.exists(sqlite_path):
        print(f"ERROR: SQLite database not found: {sqlite_path}", file=sys.stderr)
        sys.exit(1)

    try:
        import pymysql
    except ImportError:
        print("ERROR: PyMySQL not installed. Run: pip install PyMySQL", file=sys.stderr)
        sys.exit(1)

    try:
        conn_params = _parse_mysql_url(db_url)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    sq = sqlite3.connect(sqlite_path)
    tables = [
        row[0]
        for row in sq.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]

    dest = f"{conn_params['host']}:{conn_params['port']}/{conn_params['database']}"
    print(f"Initialising MySQL schema on {dest} from {sqlite_path} ...")
    print(f"  {len(tables)} tables found in SQLite\n")

    my = pymysql.connect(**conn_params, autocommit=True)
    created = 0
    errors = 0
    with my.cursor() as cur:
        for table in tables:
            ddl = translate_table(table, sq)
            if not ddl:
                continue
            try:
                cur.execute(ddl)
                print(f"  OK    {table}")
                created += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  ERROR {table}: {exc}")
                errors += 1

    sq.close()
    my.close()
    print(f"\nDone. {created} tables created/verified, {errors} errors.")


if __name__ == "__main__":
    main()
