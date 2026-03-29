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

    def test_or_replace_excludes_conflict_cols_from_set(self):
        sql = (
            "INSERT OR REPLACE INTO user_preferences "
            "(username, preferences_json, updated_at) VALUES (?,?,?)"
        )
        result = _translate_insert(sql)
        set_part = result.split("DO UPDATE SET")[1]
        assert "username=EXCLUDED" not in set_part
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
        assert "ts, key" in result

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
