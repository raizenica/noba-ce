# Enterprise v2 — Phase 2 Design: PostgreSQL Pluggable Backend

**Date:** 2026-03-27
**Branch:** `enterprise-v2` (raizenica/noba-enterprise)
**Scope:** Pluggable database backend — SQLite remains default; PostgreSQL optional via `DATABASE_URL`

---

## Context

Phase 1 delivered the Auth Triad (SAML, WebAuthn, SCIM) and API key scoping on top of `main`'s modular
architecture. The DB layer now consists of 26 domain modules, each exposing `init_schema(conn)` and a
`_XxxMixin` class, assembled into a single `Database` class via multiple inheritance in `db/core.py`.

Phase 2 adds PostgreSQL as an optional backend without touching the 26 domain modules or 22 mixins.
SQLite remains the default for community and small enterprise deployments.

---

## Goal

A single `DATABASE_URL` env var switches the backend:

```
DATABASE_URL not set (or empty)  →  SQLite at HISTORY_DB path (unchanged behaviour)
DATABASE_URL=postgresql://...    →  PostgreSQL via psycopg2
```

No code change is required to switch. No data migration is in scope for Phase 2.

---

## Architecture

### Compatibility adapter (not backend subclasses)

`DatabaseBase` (in `db/core.py`) detects the backend at `__init__` time. `Database`'s multiple-inheritance
chain is unchanged. All 26 domain modules and 22 mixins require zero changes except the handful that use
SQLite-specific constructs that cannot be auto-translated (see SQL Translation section).

```
DATABASE_URL env var
       │
       ▼
DatabaseBase.__init__()
  self._is_postgres = DATABASE_URL.startswith("postgres")
       │
  ┌────┴──────────────────────────────────────────────┐
  │ SQLite path (existing)    │ PostgreSQL path (new)   │
  │ self._conn = sqlite3...   │ self._pg_conn =         │
  │                           │   psycopg2.connect(...) │
  │                           │ self._conn =            │
  │                           │   PgConnectionAdapter() │
  └────┬──────────────────────────────────────────────┘
       │
  execute_write(fn) / execute_read(fn)
       │
  26 domain modules — UNCHANGED
  22 mixins — UNCHANGED
```

`PgConnectionAdapter` wraps a psycopg2 connection to expose the same interface as sqlite3's `Connection`:
- `execute(sql, params=())` — translates `?` → `%s`, returns `PgCursor`
- `executescript(sql)` — splits on `;`, executes each non-empty statement with schema SQL translation
- `commit()`, `rollback()`, `close()` — forwarded to underlying connection

`PgCursor` wraps a psycopg2 cursor:
- `fetchone()`, `fetchall()` — forwarded
- `rowcount` — forwarded
- `lastrowid` — raises `NotImplementedError` (see SQL Translation: `pg_insert_returning()` must be used)

### Connection model (Phase 2 — single persistent, no pool)

Identical to SQLite: one persistent write connection (protected by `self._lock: threading.RLock`),
one persistent read connection (protected by `self._read_lock: threading.Lock`). A connection pool
is deferred to Phase 3 (HA + Redis sessions).

The read connection is opened with `autocommit=True` and `options='-c default_transaction_read_only=on'`
to mirror SQLite's `query_only` pragma.

### PRAGMAs and SQLite-only operations

All SQLite-specific calls in `DatabaseBase` are guarded:

```python
if not self._is_postgres:
    conn.execute("PRAGMA journal_mode=WAL;")
    # ... etc
```

`wal_checkpoint()` becomes a no-op for PostgreSQL.

---

## SQL Translation Rules

Applied by `PgConnectionAdapter` transparently to domain module code.

### Auto-translated (zero domain module changes)

| SQLite | PostgreSQL | Applied in |
|---|---|---|
| `?` placeholder | `%s` placeholder | All `execute()` calls |
| `BLOB` | `BYTEA` | Schema DDL via `executescript()` |
| `REAL` | `DOUBLE PRECISION` | Schema DDL (SQLite REAL = 8 bytes; PG REAL = 4 bytes — precision mismatch) |
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL PRIMARY KEY` | Schema DDL |
| `INTEGER PRIMARY KEY` (no AUTOINCREMENT) | `SERIAL PRIMARY KEY` | Schema DDL |
| `executescript("a; b; c")` | Execute each statement individually | Schema init |

### Requires explicit domain module updates

Two constructs cannot be safely auto-translated:

**`INSERT OR REPLACE INTO`** — SQLite upsert syntax not valid in PostgreSQL.
Used in: `db/webauthn.py` (confirmed), possibly others (confirmed during implementation).
Fix: replace with `pg_upsert(conn, table, conflict_col, data)` helper from `db/postgres_adapter.py`.
The helper emits `INSERT ... ON CONFLICT (col) DO UPDATE SET ...` for PostgreSQL and
`INSERT OR REPLACE INTO ...` for SQLite.

**`cursor.lastrowid`** — not available via psycopg2 without `RETURNING`.
Used in: `db/healing.py` (confirmed), possibly others.
Fix: replace with `pg_insert_returning(conn, sql, params)` helper. The helper appends
`RETURNING id` for PostgreSQL and reads `cursor.lastrowid` for SQLite.

Implementation step: grep all domain modules for `INSERT OR REPLACE` and `lastrowid` to produce
the complete list before coding begins.

---

## File Map

### New files

```
share/noba-web/server/db/postgres_adapter.py
    PgConnectionAdapter   — sqlite3-compatible wrapper around psycopg2 connection
    PgCursor              — sqlite3-compatible wrapper around psycopg2 cursor
    translate_sql(sql)    — replaces ? with %s
    translate_schema_sql(sql) — maps BLOB, REAL, AUTOINCREMENT types + translate_sql
    pg_upsert(conn, table, conflict_col, cols, values) — backend-aware upsert helper
    pg_insert_returning(conn, sql, params) — backend-aware INSERT + lastrowid helper

requirements-enterprise.txt
    psycopg2-binary>=2.9
```

### Modified files

| File | Change |
|---|---|
| `server/config.py` | Add `DATABASE_URL = os.environ.get("DATABASE_URL", "")` |
| `server/db/core.py` | `DatabaseBase.__init__` detects backend; `_get_conn()`, `_get_read_conn()`, `_init_schema()`, `wal_checkpoint()` get PostgreSQL branches |
| `server/db/webauthn.py` | Replace `INSERT OR REPLACE INTO` with `pg_upsert()` |
| `server/db/healing.py` | Replace `cursor.lastrowid` with `pg_insert_returning()` |
| *(other modules using INSERT OR REPLACE or lastrowid)* | Same fix — list confirmed during implementation |
| `tests/conftest.py` | Register `postgres` marker; auto-skip postgres tests when `DATABASE_URL` unset |

### New test file

```
tests/test_postgres_backend.py   — @pytest.mark.postgres
    TestPgSchemaInit              — all 26 modules' init_schema() execute without error
    TestPgDomainRoundtrips        — one write+read per domain module
    TestPgTransactionRollback     — exception in execute_write rolls back
    TestPgConnectionRecovery      — reconnects after server restart
    TestPgUpsertHelper            — pg_upsert() conflict resolution
    TestPgInsertReturning         — pg_insert_returning() returns correct id
```

---

## Optional Dependency

`psycopg2-binary` is listed in `requirements-enterprise.txt` (not the base `requirements.txt`).
It is imported lazily inside `PostgresAdapter.__init__`:

```python
try:
    import psycopg2
except ImportError as exc:
    raise ImportError(
        "psycopg2-binary is required for PostgreSQL backend. "
        "Install with: pip install psycopg2-binary"
    ) from exc
```

If `DATABASE_URL` is not set, psycopg2 is never imported and the error is never raised.

---

## Configuration

```bash
# SQLite (default — unchanged)
# DATABASE_URL not set

# PostgreSQL
DATABASE_URL=postgresql://noba:secret@localhost:5432/noba
```

No YAML config block is needed for Phase 2 (env var only). The `HISTORY_DB` path is still used
for SQLite; when PostgreSQL is active, `HISTORY_DB` is ignored.

---

## Testing Strategy

```python
# conftest.py additions:
def pytest_configure(config):
    config.addinivalue_line("markers",
        "postgres: requires DATABASE_URL env var pointing to a PostgreSQL instance")

def pytest_collection_modifyitems(items):
    if not os.environ.get("DATABASE_URL", "").startswith("postgres"):
        skip = pytest.mark.skip(reason="DATABASE_URL not set to a PostgreSQL URL")
        for item in items:
            if "postgres" in item.keywords:
                item.add_marker(skip)
```

**Without `DATABASE_URL`:** 3259 existing tests pass, postgres tests skipped.
**With `DATABASE_URL`:** postgres tests run against a real PostgreSQL instance.

The postgres test suite (~40 tests) targets correctness of the adapter layer, not functional
parity of every route — that is covered by the SQLite test suite which runs against the
same domain module code.

---

## What Phase 2 Does NOT Include

- Connection pooling (Phase 3)
- Data migration tooling SQLite → PostgreSQL (Phase 3)
- Schema versioning / Alembic migrations (Phase 3)
- Multi-tenancy row-level security (Phase 3)
- Any frontend changes

---

## Implementation Order

1. `config.py` — add `DATABASE_URL`
2. `db/postgres_adapter.py` — `PgConnectionAdapter`, `PgCursor`, translation helpers
3. `db/core.py` — backend detection in `DatabaseBase`
4. Domain module fixes — grep and fix `INSERT OR REPLACE` + `lastrowid` usages
5. `tests/conftest.py` — postgres marker
6. `tests/test_postgres_backend.py` — postgres test suite
7. Full suite run (SQLite) + postgres suite run (if PG available)
8. Push to enterprise remote
