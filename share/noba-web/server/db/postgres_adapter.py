"""PostgreSQL compatibility adapter — wraps psycopg2 to expose the sqlite3 Connection interface."""
from __future__ import annotations

import re
from typing import Any, Sequence

# ── Conflict columns for INSERT OR REPLACE → ON CONFLICT DO UPDATE ────────────
# Key: table name (lowercase). Value: conflict column(s).
_TABLE_PK_COLS: dict[str, list[str]] = {
    "tokens":               ["token_hash"],
    "user_preferences":     ["username"],
    "webauthn_credentials": ["credential_id"],   # UNIQUE, not TEXT PK (which gets new UUID)
    "saml_sessions":        ["id"],
    "playbook_templates":   ["id"],
    "heal_suggestions":     ["category", "rule_id"],  # UNIQUE(category, rule_id)
    "linked_providers":     ["username", "provider"],  # composite PK
    "metrics_1m":           ["ts", "key"],
    "metrics_1h":           ["ts", "key"],
}

# ── Tables with SERIAL PKs — plain INSERT gets RETURNING id ──────────────────
_TABLES_WITH_AUTO_ID: frozenset[str] = frozenset({
    # automations.py
    "job_runs", "approval_queue", "maintenance_windows", "action_audit",
    # alerts.py
    "incidents",
    # security.py
    "security_scores",
    # endpoints.py
    "endpoint_monitors",
    # network.py
    "network_devices",
    # dashboards.py
    "custom_dashboards",
    # webhooks.py
    "webhook_endpoints",
    # integrations.py
    "heal_maintenance_windows", "heal_snapshots",
    # dependencies.py
    "service_dependencies",
    # baselines.py
    "config_baselines", "drift_checks",
    # backup_verify.py
    "backup_verifications", "backup_321_status",
    # healing.py
    "heal_ledger", "heal_suggestions",
    # status_page.py
    "status_components", "status_incidents", "status_updates", "incident_messages",
})

_INSERT_TABLE_RE = re.compile(
    r"^\s*INSERT\s+(?:OR\s+(?:REPLACE|IGNORE)\s+)?INTO\s+(\w+)",
    re.IGNORECASE,
)


def translate_sql(sql: str) -> str:
    """Replace SQLite ? placeholders with PostgreSQL %s."""
    return sql.replace("?", "%s")


def translate_schema_sql(sql: str) -> str:
    """Map SQLite DDL constructs to PostgreSQL equivalents, then translate placeholders."""
    sql = re.sub(r"\bBLOB\b", "BYTEA", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql, flags=re.IGNORECASE)
    sql = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "SERIAL PRIMARY KEY",
        sql, flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\b",
        "SERIAL PRIMARY KEY",
        sql, flags=re.IGNORECASE,
    )
    return translate_sql(sql)


def _translate_insert(sql: str) -> str:
    """Translate INSERT OR REPLACE / INSERT OR IGNORE to PostgreSQL ON CONFLICT syntax."""
    upper = sql.upper()

    if "INSERT OR REPLACE" in upper:
        m = _INSERT_TABLE_RE.match(sql)
        if not m:
            return sql
        table = m.group(1).lower()
        conflict_cols = _TABLE_PK_COLS.get(table)
        if not conflict_cols:
            # Unknown table — strip OR REPLACE, no conflict clause (best-effort)
            return re.sub(
                r"\bINSERT OR REPLACE INTO\b", "INSERT INTO", sql, flags=re.IGNORECASE
            )

        col_match = re.search(
            r"INSERT\s+OR\s+REPLACE\s+INTO\s+\w+\s*\(([^)]+)\)",
            sql, re.IGNORECASE,
        )
        if not col_match:
            return sql
        cols = [c.strip() for c in col_match.group(1).split(",")]
        conflict_set = {p.lower() for p in conflict_cols}
        non_pk = [c for c in cols if c.lower() not in conflict_set]
        update_set = ", ".join(f"{c}=EXCLUDED.{c}" for c in non_pk)
        conflict_target = ", ".join(conflict_cols)

        base = re.sub(
            r"\bINSERT OR REPLACE INTO\b", "INSERT INTO", sql, flags=re.IGNORECASE
        )
        suffix = f" ON CONFLICT ({conflict_target}) DO UPDATE SET {update_set}"
        if table in _TABLES_WITH_AUTO_ID:
            suffix += " RETURNING id"
        return base.rstrip().rstrip(";") + suffix

    if "INSERT OR IGNORE" in upper:
        base = re.sub(
            r"\bINSERT OR IGNORE INTO\b", "INSERT INTO", sql, flags=re.IGNORECASE
        )
        return base.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"

    return sql


def _maybe_add_returning(sql: str) -> str:
    """Append RETURNING id to a plain INSERT if the target table uses a SERIAL PK."""
    if "RETURNING" in sql.upper():
        return sql
    m = _INSERT_TABLE_RE.match(sql)
    if not m:
        return sql
    table = m.group(1).lower()
    if table in _TABLES_WITH_AUTO_ID:
        return sql.rstrip().rstrip(";") + " RETURNING id"
    return sql


class PgCursor:
    """sqlite3-compatible cursor wrapper around a psycopg2 cursor."""

    def __init__(self, pg_cursor, *, _has_returning_id: bool = False) -> None:
        self._cur = pg_cursor
        self.rowcount: int = pg_cursor.rowcount
        self._lastrowid: int | None = None
        if _has_returning_id:
            row = pg_cursor.fetchone()
            self._lastrowid = row[0] if row else None

    @property
    def lastrowid(self) -> int | None:
        return self._lastrowid

    @property
    def description(self):
        return self._cur.description

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)


class PgConnectionAdapter:
    """Wraps a psycopg2 connection to expose the sqlite3 Connection interface."""

    def __init__(self, pg_conn) -> None:
        self._conn = pg_conn

    def execute(self, sql: str, params: Sequence[Any] = ()) -> PgCursor:
        stripped_upper = sql.strip().upper()
        has_returning = False

        if stripped_upper.startswith(("CREATE", "ALTER", "DROP")):
            sql = translate_schema_sql(sql)
        elif stripped_upper.startswith("INSERT"):
            if "OR REPLACE" in stripped_upper or "OR IGNORE" in stripped_upper:
                sql = _translate_insert(sql)
                has_returning = "RETURNING ID" in sql.upper()
            else:
                sql = _maybe_add_returning(sql)
                has_returning = "RETURNING ID" in sql.upper()
            sql = translate_sql(sql)
        else:
            sql = translate_sql(sql)

        cur = self._conn.cursor()
        cur.execute(sql, params)
        return PgCursor(cur, _has_returning_id=has_returning)

    def executemany(self, sql: str, seq_of_params) -> None:
        """Execute the same statement for each param tuple (sqlite3 compat)."""
        for params in seq_of_params:
            self.execute(sql, params)

    def executescript(self, sql: str) -> None:
        """Execute a multi-statement DDL script (used by init_schema functions)."""
        for stmt in sql.split(";"):
            stmt = translate_schema_sql(stmt).strip()
            if stmt:
                cur = self._conn.cursor()
                cur.execute(stmt)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()
