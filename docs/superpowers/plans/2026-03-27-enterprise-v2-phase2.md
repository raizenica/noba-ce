# Enterprise v2 Phase 2 — PostgreSQL Pluggable Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make NOBA's database backend pluggable — SQLite remains the default; setting `DATABASE_URL=postgresql://...` switches to PostgreSQL with zero domain module changes.

**Architecture:** `PgConnectionAdapter` wraps a psycopg2 connection to expose the sqlite3 `Connection` interface. Auto-translation handles `?→%s`, DDL type conversions, `INSERT OR REPLACE→ON CONFLICT DO UPDATE`, `INSERT OR IGNORE→ON CONFLICT DO NOTHING`, and `lastrowid` via `RETURNING id`. `DatabaseBase` detects the backend at `__init__` time via `DATABASE_URL`.

**Tech Stack:** Python 3.11+, psycopg2-binary (optional, only imported when DATABASE_URL is set), pytest with `@pytest.mark.postgres` marker.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `share/noba-web/server/config.py` | Modify | Add `DATABASE_URL` env var |
| `share/noba-web/server/db/postgres_adapter.py` | Create | Full adapter: `PgConnectionAdapter`, `PgCursor`, translation logic |
| `share/noba-web/server/db/core.py` | Modify | Backend detection, PostgreSQL branches in `DatabaseBase` |
| `tests/conftest.py` | Modify | Add `postgres` marker + auto-skip logic |
| `tests/test_postgres_backend.py` | Create | `@pytest.mark.postgres` test suite |

---

## Task 1: Add DATABASE_URL to config.py

**Files:**
- Modify: `share/noba-web/server/config.py:25` (after HISTORY_DB line)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_database_url.py
from __future__ import annotations
import os

def test_database_url_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import importlib
    import server.config as cfg
    importlib.reload(cfg)
    assert cfg.DATABASE_URL == ""

def test_database_url_reads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    import importlib
    import server.config as cfg
    importlib.reload(cfg)
    assert cfg.DATABASE_URL == "postgresql://user:pass@localhost/db"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/raizen/noba/.worktrees/enterprise-v2
pytest tests/test_config_database_url.py -v
```
Expected: `AttributeError: module 'server.config' has no attribute 'DATABASE_URL'`

- [ ] **Step 3: Add DATABASE_URL to config.py**

In `share/noba-web/server/config.py`, after line 25 (`HISTORY_DB = ...`), add:

```python
DATABASE_URL  = os.environ.get("DATABASE_URL", "")
```

- [ ] **Step 4: Run ruff and test**

```bash
ruff check --fix share/noba-web/server/config.py
pytest tests/test_config_database_url.py -v
```
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/config.py tests/test_config_database_url.py
git commit -m "feat(phase2): add DATABASE_URL to config — PostgreSQL backend selector"
```

---

## Task 2: Create db/postgres_adapter.py

**Files:**
- Create: `share/noba-web/server/db/postgres_adapter.py`
- Test: `tests/test_postgres_adapter_unit.py`

- [ ] **Step 1: Write unit tests for translation helpers**

```python
# tests/test_postgres_adapter_unit.py
"""Unit tests for postgres_adapter translation logic — no PostgreSQL required."""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "share", "noba-web"))

from server.db.postgres_adapter import (
    translate_sql,
    translate_schema_sql,
    _translate_insert,
    _maybe_add_returning,
    _TABLE_PK_COLS,
    _TABLES_WITH_AUTO_ID,
)


class TestTranslateSql:
    def test_replaces_question_marks_with_percent_s(self):
        assert translate_sql("SELECT * FROM t WHERE id=?") == "SELECT * FROM t WHERE id=%s"

    def test_replaces_multiple_placeholders(self):
        result = translate_sql("INSERT INTO t (a,b) VALUES (?,?)")
        assert result == "INSERT INTO t (a,b) VALUES (%s,%s)"

    def test_no_placeholders_unchanged(self):
        sql = "SELECT * FROM t"
        assert translate_sql(sql) == sql


class TestTranslateSchemaSql:
    def test_blob_to_bytea(self):
        assert "BYTEA" in translate_schema_sql("CREATE TABLE t (x BLOB)")
        assert "BLOB" not in translate_schema_sql("CREATE TABLE t (x BLOB)")

    def test_real_to_double_precision(self):
        result = translate_schema_sql("CREATE TABLE t (x REAL DEFAULT 0)")
        assert "DOUBLE PRECISION" in result
        assert "REAL" not in result

    def test_autoincrement_to_serial(self):
        result = translate_schema_sql("id INTEGER PRIMARY KEY AUTOINCREMENT,")
        assert "SERIAL PRIMARY KEY" in result
        assert "AUTOINCREMENT" not in result

    def test_integer_pk_without_autoincrement_to_serial(self):
        result = translate_schema_sql("id INTEGER PRIMARY KEY,")
        assert "SERIAL PRIMARY KEY" in result

    def test_also_replaces_placeholders(self):
        result = translate_schema_sql("ALTER TABLE t ADD COLUMN x REAL DEFAULT ?")
        assert "%s" in result
        assert "?" not in result
        assert "DOUBLE PRECISION" in result


class TestTranslateInsert:
    def test_or_replace_to_on_conflict_do_update(self):
        sql = (
            "INSERT OR REPLACE INTO tokens "
            "(token_hash, username, role) VALUES (?,?,?)"
        )
        result = _translate_insert(sql)
        assert "ON CONFLICT" in result
        assert "INSERT OR REPLACE" not in result
        assert "DO UPDATE SET" in result
        assert "token_hash" in result  # conflict column present

    def test_or_replace_excludes_conflict_cols_from_set(self):
        sql = (
            "INSERT OR REPLACE INTO user_preferences "
            "(username, preferences_json, updated_at) VALUES (?,?,?)"
        )
        result = _translate_insert(sql)
        # username is conflict col — must NOT appear in SET clause
        set_part = result.split("DO UPDATE SET")[1]
        assert "username=EXCLUDED" not in set_part
        # non-conflict cols must appear
        assert "preferences_json=EXCLUDED.preferences_json" in set_part
        assert "updated_at=EXCLUDED.updated_at" in set_part

    def test_or_replace_heal_suggestions_adds_returning(self):
        sql = (
            "INSERT OR REPLACE INTO heal_suggestions "
            "(category, severity, message, rule_id, suggested_action, evidence, dismissed, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,0,?,?)"
        )
        result = _translate_insert(sql)
        assert "RETURNING id" in result

    def test_or_replace_tokens_no_returning(self):
        # tokens is NOT in _TABLES_WITH_AUTO_ID — no RETURNING
        sql = "INSERT OR REPLACE INTO tokens (token_hash, username, role) VALUES (?,?,?)"
        result = _translate_insert(sql)
        assert "RETURNING id" not in result

    def test_or_replace_metrics_1m_select_form(self):
        sql = (
            "INSERT OR REPLACE INTO metrics_1m (ts, key, value) "
            "SELECT ?, metric, AVG(value) FROM metrics WHERE ts >= ? AND ts < ? GROUP BY metric HAVING COUNT(*) > 0"
        )
        result = _translate_insert(sql)
        assert "ON CONFLICT" in result
        assert "ts, key" in result  # composite conflict cols

    def test_or_ignore_to_on_conflict_do_nothing(self):
        sql = "INSERT OR IGNORE INTO agents (id, name) VALUES (?,?)"
        result = _translate_insert(sql)
        assert "ON CONFLICT DO NOTHING" in result
        assert "INSERT OR IGNORE" not in result

    def test_plain_insert_unchanged(self):
        sql = "INSERT INTO t (a) VALUES (?)"
        result = _translate_insert(sql)
        assert "ON CONFLICT" not in result
        assert result == sql


class TestMaybeAddReturning:
    def test_adds_returning_for_autoincrement_table(self):
        sql = "INSERT INTO heal_ledger (a, b) VALUES (?,?)"
        result = _maybe_add_returning(sql)
        assert "RETURNING id" in result

    def test_no_returning_for_non_autoincrement_table(self):
        sql = "INSERT INTO tokens (token_hash, username) VALUES (?,?)"
        result = _maybe_add_returning(sql)
        assert "RETURNING id" not in result

    def test_no_duplicate_returning(self):
        sql = "INSERT INTO heal_ledger (a) VALUES (?) RETURNING id"
        result = _maybe_add_returning(sql)
        assert result.count("RETURNING id") == 1


class TestTableDataStructures:
    def test_table_pk_cols_covers_all_or_replace_tables(self):
        expected = {
            "tokens", "user_preferences", "webauthn_credentials",
            "saml_sessions", "playbook_templates", "heal_suggestions",
            "linked_providers", "metrics_1m", "metrics_1h",
        }
        assert set(_TABLE_PK_COLS.keys()) == expected

    def test_tables_with_auto_id_is_frozenset(self):
        assert isinstance(_TABLES_WITH_AUTO_ID, frozenset)

    def test_heal_ledger_in_auto_id(self):
        assert "heal_ledger" in _TABLES_WITH_AUTO_ID

    def test_incidents_in_auto_id(self):
        assert "incidents" in _TABLES_WITH_AUTO_ID
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_postgres_adapter_unit.py -v
```
Expected: ImportError `No module named 'server.db.postgres_adapter'`

- [ ] **Step 3: Create db/postgres_adapter.py**

```python
# share/noba-web/server/db/postgres_adapter.py
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
```

- [ ] **Step 4: Run ruff and unit tests**

```bash
ruff check --fix share/noba-web/server/db/postgres_adapter.py
pytest tests/test_postgres_adapter_unit.py -v
```
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/db/postgres_adapter.py tests/test_postgres_adapter_unit.py
git commit -m "feat(phase2): add db/postgres_adapter.py — PgConnectionAdapter + SQL translation"
```

---

## Task 3: Modify db/core.py — Backend Detection

**Files:**
- Modify: `share/noba-web/server/db/core.py`

- [ ] **Step 1: Write test that verifies SQLite path is unchanged**

The existing test suite covers SQLite — run it to get a baseline before modifying core.py.

```bash
pytest tests/ -v --tb=short -q 2>&1 | tail -5
```
Expected: `3259 passed` (or current count) with no failures.

- [ ] **Step 2: Modify db/core.py**

Replace the entire file content with the following. All logic not related to PostgreSQL is preserved verbatim:

```python
"""Noba – Thread-safe SQLite/PostgreSQL database layer (core)."""
from __future__ import annotations

import logging
import os
import sqlite3
import threading

from ..config import DATABASE_URL, HISTORY_DB
from . import (
    agents, alerts, api_keys, audit, automations, backup_verify,
    baselines, dashboards, dependencies, endpoints, healing,
    integrations, linked_providers, metrics, network,
    notifications, saml, scim, security, status_page, tokens,
    user_dashboards, user_preferences, webhooks, webauthn,
)
from .agents import _AgentsMixin
from .alerts import _AlertsMixin
from .api_keys import _ApiKeysMixin
from .audit import _AuditMixin
from .automations import _ApprovalsMixin, _AutomationsMixin
from .backup_verify import _BackupVerifyMixin
from .baselines import _BaselinesMixin
from .dashboards import _DashboardsMixin
from .dependencies import _DependenciesMixin
from .endpoints import _EndpointsMixin
from .healing import _HealingMixin
from .integrations import _IntegrationsMixin
from .linked_providers import _LinkedProvidersMixin
from .metrics import _MetricsMixin
from .notifications import _NotificationsMixin
from .saml import _SamlMixin
from .scim import _ScimMixin
from .security import _SecurityMixin
from .status_page import _StatusPageMixin
from .tokens import _TokensMixin
from .user_dashboards import _UserDashboardsMixin
from .user_preferences import _UserPreferencesMixin
from .webhooks import _WebhooksMixin
from .webauthn import _WebAuthnMixin

logger = logging.getLogger("noba")

_SCHEMA_MODULES = [
    metrics, audit, automations, alerts, api_keys, tokens,
    notifications, user_dashboards, user_preferences, agents,
    endpoints, dashboards, status_page, security, dependencies,
    baselines, network, webhooks, backup_verify, healing,
    integrations, linked_providers, saml, scim, webauthn,
]


def _run_alter_migrations(conn) -> None:
    """Idempotent additive column migrations. Swallows duplicate-column errors
    from both SQLite ('duplicate column name') and PostgreSQL ('already exists').
    """
    migrations = [
        "ALTER TABLE status_incidents ADD COLUMN assigned_to TEXT",
        "ALTER TABLE approval_queue ADD COLUMN workflow_context TEXT",
        "ALTER TABLE integration_instances ADD COLUMN verify_ssl INTEGER DEFAULT 1",
        "ALTER TABLE integration_instances ADD COLUMN ca_bundle TEXT",
        "ALTER TABLE heal_ledger ADD COLUMN risk_level TEXT",
        "ALTER TABLE heal_ledger ADD COLUMN snapshot_id INTEGER",
        "ALTER TABLE heal_ledger ADD COLUMN rollback_status TEXT",
        "ALTER TABLE heal_ledger ADD COLUMN dependency_root TEXT",
        "ALTER TABLE heal_ledger ADD COLUMN suppressed_by TEXT",
        "ALTER TABLE heal_ledger ADD COLUMN maintenance_window_id INTEGER",
        "ALTER TABLE heal_ledger ADD COLUMN instance_id TEXT",
        "ALTER TABLE api_keys ADD COLUMN scope TEXT DEFAULT ''",
        "ALTER TABLE api_keys ADD COLUMN allowed_ips TEXT DEFAULT '[]'",
        "ALTER TABLE api_keys ADD COLUMN rate_limit INTEGER DEFAULT 0",
        "ALTER TABLE scim_tokens ADD COLUMN expires_at REAL DEFAULT 0",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise
        except Exception as e:
            # PostgreSQL raises DuplicateColumn — message contains "already exists"
            if "already exists" not in str(e).lower():
                raise


class DatabaseBase:
    """Connection management, schema init, and WAL checkpoint. No domain logic."""

    def __init__(self, path: str = HISTORY_DB) -> None:
        self._path = path
        self._is_postgres = DATABASE_URL.lower().startswith("postgres")
        self._lock = threading.RLock()      # write lock (RLock for reentrancy)
        self._read_lock = threading.Lock()  # read lock (protects read conn)
        self._conn = None
        self._read_conn = None
        self._pg_conn = None       # raw psycopg2 write connection
        self._pg_read_conn = None  # raw psycopg2 read connection
        if not self._is_postgres:
            parent = os.path.dirname(self._path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        self._init_schema()

    def _get_conn(self):
        """Return persistent write connection, creating if needed.

        WARNING: Callers MUST hold self._lock for writes, or use
        execute_write()/transaction() which handle locking automatically.
        """
        if self._is_postgres:
            if self._conn is None:
                try:
                    import psycopg2
                except ImportError as exc:
                    raise ImportError(
                        "psycopg2-binary is required for PostgreSQL backend. "
                        "Install with: pip install psycopg2-binary"
                    ) from exc
                from .postgres_adapter import PgConnectionAdapter
                self._pg_conn = psycopg2.connect(DATABASE_URL)
                self._pg_conn.autocommit = False
                self._conn = PgConnectionAdapter(self._pg_conn)
            return self._conn

        # SQLite path (unchanged)
        if self._conn is None:
            self._conn = sqlite3.connect(self._path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            cur_av = self._conn.execute("PRAGMA auto_vacuum;").fetchone()[0]
            if cur_av != 2:  # 2 = INCREMENTAL
                self._conn.execute("PRAGMA auto_vacuum=INCREMENTAL;")
                self._conn.execute("VACUUM;")
        return self._conn

    def _get_read_conn(self):
        """Return a read-only connection for concurrent reads."""
        if self._is_postgres:
            if self._read_conn is None:
                try:
                    import psycopg2
                except ImportError as exc:
                    raise ImportError(
                        "psycopg2-binary is required for PostgreSQL backend. "
                        "Install with: pip install psycopg2-binary"
                    ) from exc
                from .postgres_adapter import PgConnectionAdapter
                self._pg_read_conn = psycopg2.connect(
                    DATABASE_URL,
                    options="-c default_transaction_read_only=on",
                )
                self._pg_read_conn.autocommit = True
                self._read_conn = PgConnectionAdapter(self._pg_read_conn)
            return self._read_conn

        # SQLite path (unchanged)
        if self._path == ":memory:":
            return self._get_conn()
        if self._read_conn is None:
            self._read_conn = sqlite3.connect(
                self._path, check_same_thread=False,
                isolation_level=None,  # autocommit
            )
            self._read_conn.execute("PRAGMA journal_mode=WAL;")
            self._read_conn.execute("PRAGMA synchronous=NORMAL;")
            self._read_conn.execute("PRAGMA busy_timeout=5000;")
            self._read_conn.execute("PRAGMA foreign_keys=ON;")
            self._read_conn.execute("PRAGMA query_only=ON;")
        return self._read_conn

    def execute_read(self, fn):
        """Execute a read operation without acquiring the write lock."""
        conn = self._get_read_conn()
        return fn(conn)

    def execute_write(self, fn):
        """Execute a write operation with proper lock + connection isolation."""
        with self._lock:
            conn = self._get_conn()
            result = fn(conn)
            conn.commit()
            return result

    def transaction(self, fn):
        """Execute multiple operations in a single atomic transaction."""
        with self._lock:
            conn = self._get_conn()
            try:
                result = fn(conn)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._get_conn()
            for mod in _SCHEMA_MODULES:
                mod.init_schema(conn)
            _run_alter_migrations(conn)
            conn.commit()
        # Seed default playbook templates outside the lock block to avoid deadlock
        automations._seed_default_playbooks(self._get_conn(), self._lock)

    def wal_checkpoint(self) -> None:
        """Run WAL checkpoint. No-op for PostgreSQL (WAL is managed by PG itself)."""
        if self._is_postgres:
            return
        with self._lock:
            self._get_conn().execute("PRAGMA wal_checkpoint(TRUNCATE);")


class Database(
    DatabaseBase,
    _MetricsMixin, _AuditMixin, _AutomationsMixin, _AlertsMixin,
    _ApiKeysMixin, _TokensMixin, _NotificationsMixin, _UserDashboardsMixin,
    _UserPreferencesMixin, _AgentsMixin, _EndpointsMixin,
    _DashboardsMixin, _StatusPageMixin, _SecurityMixin, _DependenciesMixin,
    _BaselinesMixin, _WebhooksMixin, _BackupVerifyMixin,
    _ApprovalsMixin, _HealingMixin, _IntegrationsMixin, _LinkedProvidersMixin,
    _SamlMixin, _ScimMixin, _WebAuthnMixin,
):
    """Thread-safe database with all domain methods via mixins (SQLite or PostgreSQL)."""

    # Network delegation methods (no mixin per spec)
    def upsert_network_device(self, ip: str, mac: str | None = None,
                              hostname: str | None = None,
                              vendor: str | None = None,
                              open_ports: list[int] | None = None,
                              discovered_by: str | None = None) -> int | None:
        return network.upsert_device(self._get_conn(), self._lock, ip, mac=mac,
                                     hostname=hostname, vendor=vendor,
                                     open_ports=open_ports, discovered_by=discovered_by)

    def list_network_devices(self) -> list[dict]:
        return network.list_devices(self._get_read_conn(), self._read_lock)

    def get_network_device(self, device_id: int) -> dict | None:
        return network.get_device(self._get_read_conn(), self._read_lock, device_id)

    def delete_network_device(self, device_id: int) -> bool:
        return network.delete_device(self._get_conn(), self._lock, device_id)
```

- [ ] **Step 3: Run ruff**

```bash
ruff check --fix share/noba-web/server/db/core.py
```
Expected: no errors

- [ ] **Step 4: Run full SQLite test suite to confirm no regression**

```bash
pytest tests/ -v --tb=short -q 2>&1 | tail -10
```
Expected: same pass count as before (no new failures), postgres tests skipped.

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/db/core.py
git commit -m "feat(phase2): db/core.py — PostgreSQL backend detection and dual-path connections"
```

---

## Task 4: conftest.py + test_postgres_backend.py

**Files:**
- Modify: `tests/conftest.py`
- Create: `tests/test_postgres_backend.py`

- [ ] **Step 1: Add postgres marker to conftest.py**

At the end of `tests/conftest.py`, append:

```python
import os as _os


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "postgres: requires DATABASE_URL env var pointing to a live PostgreSQL instance",
    )


def pytest_collection_modifyitems(items):
    if not _os.environ.get("DATABASE_URL", "").lower().startswith("postgres"):
        skip = pytest.mark.skip(reason="DATABASE_URL not set to a PostgreSQL URL")
        for item in items:
            if "postgres" in item.keywords:
                item.add_marker(skip)
```

- [ ] **Step 2: Verify the marker works**

```bash
pytest tests/ -v -q --collect-only 2>&1 | grep "postgres" | head -5
# Expected: any @pytest.mark.postgres tests show up (none yet — that's fine)
pytest tests/ -q 2>&1 | tail -5
```
Expected: existing suite passes, no new failures.

- [ ] **Step 3: Create tests/test_postgres_backend.py**

```python
# tests/test_postgres_backend.py
"""PostgreSQL backend tests — @pytest.mark.postgres.
Skipped automatically when DATABASE_URL is not set.
Run with: DATABASE_URL=postgresql://... pytest tests/test_postgres_backend.py -v
"""
from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def pg_db():
    """Module-scoped Database instance using DATABASE_URL (PostgreSQL)."""
    from server.db.core import Database
    db = Database()
    yield db
    # cleanup: close connections
    if db._pg_conn:
        db._pg_conn.close()
    if db._pg_read_conn:
        db._pg_read_conn.close()


class TestPgSchemaInit:
    """All 26 init_schema() calls execute without error on PostgreSQL."""

    def test_schema_initialized_without_error(self, pg_db):
        # If we got here, __init__ ran _init_schema successfully
        assert pg_db._is_postgres is True

    def test_write_connection_is_adapter(self, pg_db):
        from server.db.postgres_adapter import PgConnectionAdapter
        conn = pg_db._get_conn()
        assert isinstance(conn, PgConnectionAdapter)

    def test_read_connection_is_adapter(self, pg_db):
        from server.db.postgres_adapter import PgConnectionAdapter
        conn = pg_db._get_read_conn()
        assert isinstance(conn, PgConnectionAdapter)


class TestPgTransactionRollback:
    """Exception inside execute_write() rolls back the transaction."""

    def test_rollback_on_exception(self, pg_db):
        """Insert should be rolled back if an exception occurs mid-transaction."""
        unique_name = f"__rollback_test_{int(time.time())}"

        def _bad_write(conn):
            conn.execute(
                "INSERT INTO custom_dashboards (name, layout_json, created_by) "
                "VALUES (?,?,?)",
                (unique_name, "[]", "test"),
            )
            raise RuntimeError("intentional failure")

        with pytest.raises(RuntimeError):
            pg_db.transaction(_bad_write)

        # Row must not exist after rollback
        rows = pg_db.execute_read(
            lambda conn: conn.execute(
                "SELECT id FROM custom_dashboards WHERE name=?", (unique_name,)
            ).fetchall()
        )
        assert rows == []


class TestPgDomainRoundtrips:
    """One write + read per domain area to verify the adapter layer end-to-end."""

    def test_metrics_insert_and_read(self, pg_db):
        from server.db import metrics
        conn = pg_db._get_conn()
        lock = pg_db._lock
        metrics.insert_metric(conn, lock, metric="cpu_percent", value=42.5)
        rows = pg_db.execute_read(
            lambda c: c.execute(
                "SELECT value FROM metrics WHERE metric=%s ORDER BY timestamp DESC LIMIT 1",
                ("cpu_percent",),
            ).fetchone()
        )
        assert rows is not None
        assert abs(rows[0] - 42.5) < 0.01

    def test_user_preferences_upsert_roundtrip(self, pg_db):
        from server.db import user_preferences
        conn = pg_db._get_conn()
        lock = pg_db._lock
        prefs = {"theme": "dracula", "sidebar": True}
        user_preferences.save_user_preferences(conn, lock, "__pg_test_user", prefs)
        result = pg_db.execute_read(
            lambda c: c.execute(
                "SELECT preferences_json FROM user_preferences WHERE username=%s",
                ("__pg_test_user",),
            ).fetchone()
        )
        assert result is not None
        import json
        assert json.loads(result[0]) == prefs

    def test_user_preferences_upsert_updates_on_conflict(self, pg_db):
        from server.db import user_preferences
        conn = pg_db._get_conn()
        lock = pg_db._lock
        user_preferences.save_user_preferences(conn, lock, "__pg_upsert_user", {"v": 1})
        user_preferences.save_user_preferences(conn, lock, "__pg_upsert_user", {"v": 2})
        result = pg_db.execute_read(
            lambda c: c.execute(
                "SELECT preferences_json FROM user_preferences WHERE username=%s",
                ("__pg_upsert_user",),
            ).fetchone()
        )
        import json
        assert json.loads(result[0]) == {"v": 2}  # second write wins

    def test_heal_ledger_insert_returns_id(self, pg_db):
        from server.db import healing
        conn = pg_db._get_conn()
        lock = pg_db._lock
        row_id = healing.insert_heal_outcome(
            conn, lock,
            rule_id="pg_test_rule",
            condition="test_condition",
            action_type="test_action",
        )
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_incidents_insert_returns_id(self, pg_db):
        from server.db import alerts
        conn = pg_db._get_conn()
        lock = pg_db._lock
        incident_id = alerts.insert_incident(
            conn, lock, severity="info", source="pg_test", title="PG Test Incident"
        )
        assert isinstance(incident_id, int)
        assert incident_id > 0

    def test_network_device_upsert_returns_id(self, pg_db):
        device_id = pg_db.upsert_network_device(
            "192.168.99.1", hostname="pg-test-host"
        )
        assert device_id is not None
        assert device_id > 0

    def test_heal_suggestions_insert_or_replace_returns_id(self, pg_db):
        from server.db import healing
        conn = pg_db._get_conn()
        lock = pg_db._lock
        # First upsert
        first_id = healing.upsert_heal_suggestion(
            conn, lock, category="pg_test", severity="info", message="test"
        )
        assert isinstance(first_id, int)
        # Second upsert with same category — should update, return same or new id
        second_id = healing.upsert_heal_suggestion(
            conn, lock, category="pg_test", severity="warn", message="updated"
        )
        assert isinstance(second_id, int)

    def test_tokens_insert_or_replace_no_duplicate(self, pg_db):
        from server.db import tokens
        conn = pg_db._get_conn()
        lock = pg_db._lock
        import hashlib, time as _time
        h = hashlib.sha256(b"pg_test_token").hexdigest()
        now = int(_time.time())
        tokens._insert_token(conn, lock, h, "pg_test_user", "viewer", now, now + 3600)
        tokens._insert_token(conn, lock, h, "pg_test_user", "admin", now, now + 7200)
        # Only one row should exist for this hash
        rows = pg_db.execute_read(
            lambda c: c.execute(
                "SELECT role FROM tokens WHERE token_hash=%s", (h,)
            ).fetchall()
        )
        assert len(rows) == 1
        assert rows[0][0] == "admin"  # second write wins

    def test_metrics_rollup_insert_or_replace_select_form(self, pg_db):
        """The INSERT OR REPLACE ... SELECT form (metrics rollup) works on PostgreSQL."""
        from server.db import metrics
        conn = pg_db._get_conn()
        lock = pg_db._lock
        # Insert raw metric data first
        metrics.insert_metric(conn, lock, metric="cpu_percent", value=55.0)
        # Rollup to 1m — this uses INSERT OR REPLACE INTO metrics_1m ... SELECT
        metrics.rollup_to_1m(conn, lock)
        # No exception = success


class TestPgWalCheckpoint:
    """wal_checkpoint() is a no-op for PostgreSQL."""

    def test_wal_checkpoint_noop(self, pg_db):
        # Must not raise
        pg_db.wal_checkpoint()
```

- [ ] **Step 4: Run full SQLite suite to confirm no regression**

```bash
pytest tests/ -v --tb=short -q --ignore=tests/test_postgres_backend.py 2>&1 | tail -5
```
Expected: same pass count as before.

- [ ] **Step 5: Verify postgres tests are auto-skipped without DATABASE_URL**

```bash
pytest tests/test_postgres_backend.py -v 2>&1 | head -20
```
Expected: all tests show `SKIPPED [reason: DATABASE_URL not set to a PostgreSQL URL]`

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/test_postgres_backend.py
git commit -m "feat(phase2): add postgres marker to conftest + PostgreSQL test suite"
```

---

## Task 5: Full Suite Run + Push

**Files:** None (verification only)

- [ ] **Step 1: Run full SQLite suite**

```bash
cd /home/raizen/noba/.worktrees/enterprise-v2
pytest tests/ -v --tb=short -q 2>&1 | tail -10
```
Expected: all existing tests pass, postgres tests skipped.

- [ ] **Step 2: Run ruff on all modified files**

```bash
ruff check share/noba-web/server/config.py \
           share/noba-web/server/db/core.py \
           share/noba-web/server/db/postgres_adapter.py
```
Expected: no errors

- [ ] **Step 3: Add psycopg2-binary to requirements-enterprise.txt**

Create `requirements-enterprise.txt` in the repo root:

```
# Enterprise-tier optional dependencies
psycopg2-binary>=2.9
```

```bash
git add requirements-enterprise.txt
```

- [ ] **Step 4: Push to enterprise remote**

```bash
git push enterprise enterprise-v2
```
Expected: push succeeds

- [ ] **Step 5: Verify final commit log**

```bash
git log --oneline -8
```
Expected: see Phase 2 commits (config, adapter, core, tests, requirements) followed by Phase 1 commits.

---

## Self-Review Checklist

**Spec coverage:**
- [x] `DATABASE_URL` env var → Task 1
- [x] `PgConnectionAdapter` wrapping psycopg2 → Task 2
- [x] `?` → `%s` translation → Task 2 (`translate_sql`)
- [x] `BLOB` → `BYTEA`, `REAL` → `DOUBLE PRECISION`, `INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL PRIMARY KEY` → Task 2 (`translate_schema_sql`)
- [x] `INSERT OR REPLACE` → `ON CONFLICT DO UPDATE` → Task 2 (`_translate_insert`)
- [x] `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING` → Task 2 (`_translate_insert`)
- [x] `lastrowid` via `RETURNING id` → Task 2 (`_maybe_add_returning` + `PgCursor`)
- [x] Backend detection in `DatabaseBase.__init__` → Task 3
- [x] PRAGMA calls guarded by `if not self._is_postgres` → Task 3
- [x] `wal_checkpoint()` no-op for PostgreSQL → Task 3
- [x] `_run_alter_migrations` handles PostgreSQL DuplicateColumn error → Task 3
- [x] `@pytest.mark.postgres` marker + auto-skip → Task 4
- [x] `psycopg2-binary` lazy import with helpful error message → Task 3
- [x] `requirements-enterprise.txt` with `psycopg2-binary>=2.9` → Task 5
- [x] Zero domain module changes → verified (only config.py, core.py, new postgres_adapter.py)

**Key data structures verified against codebase:**
- `_TABLE_PK_COLS`: 9 entries covering all `INSERT OR REPLACE` usages
- `_TABLES_WITH_AUTO_ID`: 21 tables covering all `cursor.lastrowid` usages
- `metrics_1m`/`metrics_1h` INSERT OR REPLACE uses SELECT form — handled by regex in `_translate_insert`
- `heal_suggestions` uses both `INSERT OR REPLACE` AND `lastrowid` — handled by checking `_TABLES_WITH_AUTO_ID` within `_translate_insert`
