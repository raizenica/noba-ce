# ADR-001: Dual-Connection SQLite with Explicit `(conn, lock, ...)` Pattern

**Status:** Accepted
**Date:** 2026-01-15
**Deciders:** Raizen

---

## Context

NOBA runs a FastAPI backend with multiple concurrent request handlers (async + thread pool) all sharing a single SQLite database file. SQLite's default behavior under concurrent writes causes `database is locked` errors when two threads attempt a write simultaneously.

Early versions used a single `sqlite3.connect()` at module import time with implicit locking. This caused:
- Intermittent `OperationalError: database is locked` on busy dashboards
- Hard-to-reproduce race conditions when automations and telemetry writes overlapped
- No clear contract for which code owned the connection lifecycle

Two approaches were considered:
1. **WAL + single connection** — SQLite WAL mode allows one writer + multiple readers concurrently, but a single shared connection still requires an application-level mutex
2. **Connection-per-request** — open/close on each call, avoids state sharing but has overhead and loses WAL benefits across requests

## Decision

Use **two dedicated connections** (one read-only, one write) with **explicit lock parameters** passed into every database function:

```python
# db/core.py
_read_conn  = sqlite3.connect(DB_PATH, check_same_thread=False)
_write_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_read_lock  = threading.Lock()
_write_lock = threading.Lock()
```

All DB functions in `db/automations.py` and similar modules take `(conn, lock, ...)` as their first parameters. `db/core.py` provides delegation wrappers that supply the module-level connections:

```python
# Functions accept explicit deps — easy to test, impossible to accidentally use wrong conn
def get_automations(conn, lock, ...): ...

# Core wrappers inject the real connections
def list_automations(...):
    return get_automations(_read_conn, _read_lock, ...)
```

SQLite is configured in WAL mode on startup:
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
```

## Consequences

**Positive:**
- Zero `database is locked` errors in production — the mutex serialises all writes
- Read queries never block write queries (WAL allows concurrent reads)
- Functions are pure with respect to connection state — trivially unit-testable by passing a `:memory:` connection
- The explicit `(conn, lock)` signature is self-documenting: callers cannot accidentally use the wrong connection

**Negative:**
- More verbose function signatures than a global ORM
- `VACUUM` must run outside any transaction and acquire the write lock separately — this is a known footgun (see CLAUDE.md)
- Two connections means two open file descriptors; not a concern at this scale

**Alternatives rejected:**
- SQLAlchemy/SQLModel: adds a dependency, overkill for a single-file SQLite schema
- Async SQLite (aiosqlite): would require async all the way down; existing thread-pool workers make this impractical
