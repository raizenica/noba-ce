"""Noba – Thread-safe SQLite/PostgreSQL database layer (core)."""
from __future__ import annotations

import logging
import os
import sqlite3
import threading

from ..config import DATABASE_URL, HISTORY_DB, NOBA_PG_POOL_MAX, NOBA_PG_POOL_MIN
from . import (
    agents, alerts, api_keys, audit, automations, backup_verify,
    baselines, dashboards, dependencies, endpoints, freeze, healing,
    integrations, linked_providers, login_restrict, metrics, network,
    notifications, rbac, saml, scim, security, status_page, tokens,
    user_dashboards, user_preferences, vault, password_policy,
    retention, webhooks, webauthn,
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
from .freeze import _FreezeMixin
from .healing import _HealingMixin
from .integrations import _IntegrationsMixin
from .linked_providers import _LinkedProvidersMixin
from .metrics import _MetricsMixin
from .notifications import _NotificationsMixin
from .rbac import _RBACMixin
from .saml import _SamlMixin
from .scim import _ScimMixin
from .security import _SecurityMixin
from .status_page import _StatusPageMixin
from .tenants import _TenantsMixin
from .tokens import _TokensMixin
from .user_dashboards import _UserDashboardsMixin
from .user_preferences import _UserPreferencesMixin
from .vault import _VaultMixin
from .password_policy import _PasswordPolicyMixin
from .login_restrict import _LoginRestrictMixin
from .retention import _RetentionMixin
from .webhooks import _WebhooksMixin
from .webauthn import _WebAuthnMixin

logger = logging.getLogger("noba")

_SCHEMA_MODULES = [
    metrics, audit, automations, alerts, api_keys, tokens,
    notifications, user_dashboards, user_preferences, agents,
    endpoints, dashboards, status_page, security, dependencies,
    baselines, network, webhooks, backup_verify, healing,
    integrations, linked_providers, saml, scim, webauthn, rbac, freeze, vault,
    password_policy, login_restrict, retention,
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
        # Multi-tenancy: tenant_id scoping on key tables (default = 'default')
        "ALTER TABLE integration_instances ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'",
        "ALTER TABLE automations ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'",
        "ALTER TABLE audit ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'",
        "ALTER TABLE api_keys ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'",
        # Tenant resource quotas (tenants table owned by versioned migration v6;
        # swallow "no such table" for fresh DBs — v6 CREATE TABLE already includes this column)
        "ALTER TABLE tenants ADD COLUMN limits_json TEXT NOT NULL DEFAULT '{}'",
    ]
    for sql in migrations:
        try:
            conn.execute("SAVEPOINT _alter_sp")
            conn.execute(sql)
            conn.execute("RELEASE SAVEPOINT _alter_sp")
        except sqlite3.OperationalError as e:
            conn.execute("ROLLBACK TO SAVEPOINT _alter_sp")
            err = str(e).lower()
            if "duplicate column name" not in err and "no such table" not in err:
                raise
        except Exception as e:
            # PostgreSQL raises DuplicateColumn — message contains "already exists".
            # Roll back to the savepoint so the transaction stays usable.
            try:
                conn.execute("ROLLBACK TO SAVEPOINT _alter_sp")
            except Exception:
                pass
            err_lower = str(e).lower()
            if "already exists" not in err_lower and "does not exist" not in err_lower:
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
        self._pg_conn = None            # raw psycopg2 write connection
        self._pg_read_pool = None       # ThreadedConnectionPool for reads
        self._pg_read_local = threading.local()  # per-thread read adapter
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
        """Return a read connection. PostgreSQL: per-thread checkout from pool."""
        if self._is_postgres:
            # Lazy pool creation
            if self._pg_read_pool is None:
                try:
                    from psycopg2 import pool as _pgpool
                except ImportError as exc:
                    raise ImportError(
                        "psycopg2-binary is required for PostgreSQL backend. "
                        "Install with: pip install psycopg2-binary"
                    ) from exc
                self._pg_read_pool = _pgpool.ThreadedConnectionPool(
                    NOBA_PG_POOL_MIN, NOBA_PG_POOL_MAX, DATABASE_URL,
                    options="-c default_transaction_read_only=on",
                )
            # Per-thread adapter — each thread gets its own connection from the pool
            if not hasattr(self._pg_read_local, "adapter"):
                from .postgres_adapter import PgConnectionAdapter
                pg_conn = self._pg_read_pool.getconn()
                pg_conn.autocommit = True
                self._pg_read_local.adapter = PgConnectionAdapter(pg_conn)
            return self._pg_read_local.adapter

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
        # Run versioned migrations (idempotent — skips already-applied versions).
        # Pre-seed v1–v5 as applied so the framework never re-runs migrations whose
        # tables are already owned by the _SCHEMA_MODULES init_schema() system.
        from .migrations import MIGRATIONS, _ensure_version_table, run_migrations
        import time as _time
        with self._lock:
            conn = self._get_conn()
            current = _ensure_version_table(conn)
            legacy_cutoff = 5
            if current < legacy_cutoff:
                # Bootstrap: mark all legacy schema-module migrations as done.
                # Handles fresh DBs (current=0) and partial states from earlier runs.
                now = int(_time.time())
                for m in MIGRATIONS:
                    if m["version"] <= legacy_cutoff:
                        conn.execute(
                            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?,?)",
                            (m["version"], now),
                        )
                conn.commit()
        run_migrations(self._get_conn(), self._lock)
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
    _SamlMixin, _ScimMixin, _WebAuthnMixin, _TenantsMixin,
    _RBACMixin, _FreezeMixin, _VaultMixin, _PasswordPolicyMixin,
    _LoginRestrictMixin, _RetentionMixin,
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
