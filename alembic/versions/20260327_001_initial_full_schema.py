"""Initial full schema — matches NOBA v2.0.0 internal versions v1–v6.

Revision ID: 001
Revises:
Create Date: 2026-03-27

This single migration creates the complete PostgreSQL schema from scratch.
Existing PostgreSQL installations that were bootstrapped by the NOBA server
(which auto-applies schema on startup) should stamp this revision as already
applied rather than re-running DDL:

    alembic stamp 001

Fresh installations should run:

    alembic upgrade head
"""
from __future__ import annotations

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── v1: Core infrastructure ───────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            token_hash TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at BIGINT NOT NULL,
            expires_at BIGINT NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at BIGINT NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            id SERIAL PRIMARY KEY,
            metric TEXT NOT NULL,
            value DOUBLE PRECISION NOT NULL,
            host TEXT DEFAULT '',
            timestamp BIGINT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_metrics_metric_ts ON metrics(metric, timestamp)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(timestamp)")

    # ── v2: Agents and alerts ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            hostname TEXT PRIMARY KEY,
            ip TEXT NOT NULL,
            platform TEXT,
            arch TEXT,
            agent_version TEXT,
            last_seen BIGINT NOT NULL,
            config TEXT
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS alert_history (
            id SERIAL PRIMARY KEY,
            rule_id TEXT NOT NULL,
            condition TEXT,
            target TEXT,
            severity TEXT,
            metrics TEXT,
            created_at BIGINT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_alerts_rule ON alert_history(rule_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_alerts_created ON alert_history(created_at)")

    # ── v3: Automations and healing ───────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS automations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            config TEXT NOT NULL,
            schedule TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at BIGINT NOT NULL,
            updated_at BIGINT NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'default'
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS job_runs (
            id SERIAL PRIMARY KEY,
            automation_id TEXT,
            trigger TEXT,
            triggered_by TEXT,
            status TEXT,
            started_at BIGINT,
            finished_at BIGINT,
            output TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_job_runs_automation ON job_runs(automation_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS heal_outcomes (
            id SERIAL PRIMARY KEY,
            correlation_key TEXT NOT NULL,
            rule_id TEXT,
            target TEXT,
            action_type TEXT,
            action_success INTEGER,
            verified INTEGER,
            duration_s DOUBLE PRECISION,
            created_at BIGINT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_heal_correlation ON heal_outcomes(correlation_key)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_heal_rule ON heal_outcomes(rule_id)")

    # ── v4: Audit and trust ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit (
            id SERIAL PRIMARY KEY,
            action TEXT NOT NULL,
            username TEXT,
            details TEXT,
            ip TEXT,
            created_at BIGINT NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'default'
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit(action)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit(created_at)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS trust_states (
            rule_id TEXT PRIMARY KEY,
            current_level TEXT NOT NULL,
            ceiling TEXT NOT NULL,
            promoted_at BIGINT,
            demoted_at BIGINT,
            last_evaluated BIGINT
        )
    """)

    # ── v5: Endpoints and baselines ───────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS endpoint_monitors (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            target TEXT,
            interval INTEGER DEFAULT 300,
            enabled INTEGER DEFAULT 1,
            created_at BIGINT NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS baselines (
            id SERIAL PRIMARY KEY,
            agent_group TEXT NOT NULL,
            config_type TEXT NOT NULL,
            checksum TEXT,
            content TEXT,
            created_at BIGINT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_baselines_group ON baselines(agent_group)")

    # ── Enterprise: API keys ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            key_hash TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL,
            created_at BIGINT NOT NULL,
            expires_at BIGINT,
            last_used BIGINT,
            scope TEXT DEFAULT '',
            allowed_ips TEXT DEFAULT '[]',
            rate_limit INTEGER DEFAULT 0,
            tenant_id TEXT NOT NULL DEFAULT 'default'
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)")

    # ── Enterprise: Integration instances ────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS integration_instances (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            platform TEXT NOT NULL,
            url TEXT DEFAULT '',
            auth_config TEXT DEFAULT '{}',
            site TEXT,
            tags TEXT DEFAULT '[]',
            created_at BIGINT NOT NULL,
            enabled INTEGER DEFAULT 1,
            group_id TEXT,
            verify_ssl INTEGER DEFAULT 1,
            ca_bundle TEXT,
            extra TEXT DEFAULT '{}',
            tenant_id TEXT NOT NULL DEFAULT 'default'
        )
    """)

    # ── Enterprise: SAML ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS saml_providers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            idp_metadata_url TEXT,
            idp_metadata_xml TEXT,
            sp_entity_id TEXT,
            acs_url TEXT,
            attribute_mapping TEXT DEFAULT '{}',
            enabled INTEGER DEFAULT 1,
            created_at BIGINT NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS saml_sessions (
            id TEXT PRIMARY KEY,
            username TEXT,
            provider_id TEXT,
            nameid TEXT,
            attributes TEXT DEFAULT '{}',
            created_at BIGINT NOT NULL,
            expires_at BIGINT NOT NULL
        )
    """)

    # ── Enterprise: SCIM ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS scim_tokens (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at BIGINT NOT NULL,
            expires_at DOUBLE PRECISION DEFAULT 0
        )
    """)

    # ── Enterprise: WebAuthn ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS webauthn_credentials (
            credential_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            public_key BYTEA NOT NULL,
            sign_count BIGINT NOT NULL DEFAULT 0,
            aaguid TEXT,
            fmt TEXT,
            name TEXT,
            created_at BIGINT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_webauthn_username ON webauthn_credentials(username)")

    # ── Enterprise: Linked providers ─────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS linked_providers (
            username TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_user_id TEXT,
            attributes TEXT DEFAULT '{}',
            linked_at BIGINT NOT NULL,
            PRIMARY KEY (username, provider)
        )
    """)

    # ── Enterprise: Healing infrastructure ───────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS heal_ledger (
            id SERIAL PRIMARY KEY,
            rule_id TEXT,
            target TEXT,
            action_type TEXT,
            status TEXT,
            triggered_by TEXT,
            correlation_key TEXT,
            risk_level TEXT,
            snapshot_id INTEGER,
            rollback_status TEXT,
            dependency_root TEXT,
            suppressed_by TEXT,
            maintenance_window_id INTEGER,
            instance_id TEXT,
            created_at BIGINT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_heal_ledger_rule ON heal_ledger(rule_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_heal_ledger_target ON heal_ledger(target)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS heal_suggestions (
            id SERIAL PRIMARY KEY,
            category TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            target TEXT,
            suggestion TEXT,
            confidence DOUBLE PRECISION,
            created_at BIGINT NOT NULL,
            UNIQUE (category, rule_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS heal_snapshots (
            id SERIAL PRIMARY KEY,
            target TEXT NOT NULL,
            snapshot_type TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at BIGINT NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_windows (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            start_ts BIGINT NOT NULL,
            end_ts BIGINT NOT NULL,
            targets TEXT DEFAULT '[]',
            created_by TEXT,
            created_at BIGINT NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_queue (
            id SERIAL PRIMARY KEY,
            action_type TEXT NOT NULL,
            target TEXT,
            payload TEXT DEFAULT '{}',
            status TEXT DEFAULT 'pending',
            requested_by TEXT,
            reviewed_by TEXT,
            workflow_context TEXT,
            created_at BIGINT NOT NULL,
            reviewed_at BIGINT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_queue(status)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS action_audit (
            id SERIAL PRIMARY KEY,
            action_type TEXT NOT NULL,
            target TEXT,
            outcome TEXT,
            triggered_by TEXT,
            details TEXT,
            created_at BIGINT NOT NULL
        )
    """)

    # ── Enterprise: Playbook templates ───────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS playbook_templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT,
            steps TEXT DEFAULT '[]',
            created_at BIGINT NOT NULL,
            updated_at BIGINT NOT NULL
        )
    """)

    # ── v6: Multi-tenancy ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            slug TEXT NOT NULL UNIQUE,
            created_at BIGINT NOT NULL,
            disabled INTEGER NOT NULL DEFAULT 0,
            metadata TEXT NOT NULL DEFAULT '{}'
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_members (
            tenant_id TEXT NOT NULL,
            username TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            joined_at BIGINT NOT NULL,
            PRIMARY KEY (tenant_id, username)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_tenant_members_username ON tenant_members(username)")

    # Seed default tenant
    op.execute("""
        INSERT INTO tenants (id, name, slug, created_at)
        VALUES ('default', 'Default Organization', 'default', EXTRACT(EPOCH FROM NOW())::BIGINT)
        ON CONFLICT DO NOTHING
    """)

    # ── Alembic version tracking (marks this revision as applied) ────────────
    # Note: alembic_version table is managed by Alembic itself; no manual DDL needed.


def downgrade() -> None:
    # Drop in reverse dependency order
    op.execute("DROP TABLE IF EXISTS tenant_members")
    op.execute("DROP TABLE IF EXISTS tenants")
    op.execute("DROP TABLE IF EXISTS playbook_templates")
    op.execute("DROP TABLE IF EXISTS action_audit")
    op.execute("DROP TABLE IF EXISTS approval_queue")
    op.execute("DROP TABLE IF EXISTS maintenance_windows")
    op.execute("DROP TABLE IF EXISTS heal_snapshots")
    op.execute("DROP TABLE IF EXISTS heal_suggestions")
    op.execute("DROP TABLE IF EXISTS heal_ledger")
    op.execute("DROP TABLE IF EXISTS linked_providers")
    op.execute("DROP TABLE IF EXISTS webauthn_credentials")
    op.execute("DROP TABLE IF EXISTS scim_tokens")
    op.execute("DROP TABLE IF EXISTS saml_sessions")
    op.execute("DROP TABLE IF EXISTS saml_providers")
    op.execute("DROP TABLE IF EXISTS integration_instances")
    op.execute("DROP TABLE IF EXISTS api_keys")
    op.execute("DROP TABLE IF EXISTS baselines")
    op.execute("DROP TABLE IF EXISTS endpoint_monitors")
    op.execute("DROP TABLE IF EXISTS trust_states")
    op.execute("DROP TABLE IF EXISTS audit")
    op.execute("DROP TABLE IF EXISTS heal_outcomes")
    op.execute("DROP TABLE IF EXISTS job_runs")
    op.execute("DROP TABLE IF EXISTS automations")
    op.execute("DROP TABLE IF EXISTS alert_history")
    op.execute("DROP TABLE IF EXISTS agents")
    op.execute("DROP TABLE IF EXISTS metrics")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS tokens")
