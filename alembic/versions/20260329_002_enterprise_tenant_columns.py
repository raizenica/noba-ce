"""Add tenant_id columns to tables that predate enterprise multi-tenancy.

Revision ID: 002
Revises: 001
Create Date: 2026-03-29

Adds tenant_id to audit, automations, integration_instances, and api_keys
for existing PostgreSQL installations upgrading from community to enterprise.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

_TABLES = ["audit", "automations", "integration_instances", "api_keys"]


def upgrade() -> None:
    conn = op.get_bind()
    for table in _TABLES:
        result = conn.execute(sa.text(
            "SELECT count(*) FROM information_schema.columns "
            f"WHERE table_name='{table}' AND column_name='tenant_id'"
        ))
        if result.scalar() == 0:
            op.execute(
                f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"
            )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "tenant_id")
