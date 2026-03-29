# tests/test_postgres_backend.py
"""PostgreSQL backend tests — @pytest.mark.postgres.
Skipped automatically when DATABASE_URL is not set to a PostgreSQL URL.
Run with: DATABASE_URL=postgresql://... pytest tests/test_postgres_backend.py -v
"""
from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def pg_db():
    """Module-scoped Database instance using DATABASE_URL (PostgreSQL)."""
    from server.db.core import Database
    db = Database()
    yield db
    if db._pg_conn:
        db._pg_conn.close()
    if db._pg_read_pool:
        db._pg_read_pool.closeall()


class TestPgSchemaInit:
    """All 26 init_schema() calls execute without error on PostgreSQL."""

    def test_schema_initialized_without_error(self, pg_db):
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
    """Exception inside transaction() rolls back cleanly."""

    def test_rollback_on_exception(self, pg_db):
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
        assert json.loads(result[0]) == {"v": 2}

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
        first_id = healing.upsert_heal_suggestion(
            conn, lock, category="pg_test", severity="info", message="test"
        )
        assert isinstance(first_id, int)
        second_id = healing.upsert_heal_suggestion(
            conn, lock, category="pg_test", severity="warn", message="updated"
        )
        assert isinstance(second_id, int)

    def test_tokens_insert_or_replace_no_duplicate(self, pg_db):
        from server.db import tokens
        conn = pg_db._get_conn()
        lock = pg_db._lock
        import hashlib
        h = hashlib.sha256(b"pg_test_token").hexdigest()
        now = int(time.time())
        tokens._insert_token(conn, lock, h, "pg_test_user", "viewer", now, now + 3600)
        tokens._insert_token(conn, lock, h, "pg_test_user", "admin", now, now + 7200)
        rows = pg_db.execute_read(
            lambda c: c.execute(
                "SELECT role FROM tokens WHERE token_hash=%s", (h,)
            ).fetchall()
        )
        assert len(rows) == 1
        assert rows[0][0] == "admin"

    def test_metrics_rollup_insert_or_replace_select_form(self, pg_db):
        from server.db import metrics
        conn = pg_db._get_conn()
        lock = pg_db._lock
        metrics.insert_metric(conn, lock, metric="cpu_percent", value=55.0)
        metrics.rollup_to_1m(conn, lock)
        # No exception = success


class TestPgWalCheckpoint:
    def test_wal_checkpoint_noop(self, pg_db):
        pg_db.wal_checkpoint()  # must not raise
