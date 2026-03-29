"""Alembic env.py for NOBA enterprise PostgreSQL schema management.

Reads DATABASE_URL from the environment (same variable used by the NOBA server).
Falls back to the NOBA config module if the env var is not set.

Usage:
    export DATABASE_URL="postgresql://user:pass@host:5432/noba"
    alembic upgrade head
    alembic downgrade -1
    alembic current
    alembic history
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context

# ── Resolve DATABASE_URL ──────────────────────────────────────────────────────
# Prefer the environment variable; fall back to NOBA's config module so that
# operators don't need to duplicate their connection string.
_db_url = os.environ.get("DATABASE_URL", "")
if not _db_url:
    # Add the project root to sys.path so we can import the server package
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _server_root = os.path.join(_project_root, "share", "noba-web")
    if _server_root not in sys.path:
        sys.path.insert(0, _server_root)
    try:
        from server.config import DATABASE_URL as _db_url  # type: ignore[assignment]
    except ImportError:
        pass

if not _db_url or not _db_url.lower().startswith("postgres"):
    raise SystemExit(
        "NOBA Alembic: DATABASE_URL must be set to a PostgreSQL connection string.\n"
        "Example: export DATABASE_URL='postgresql://noba:secret@localhost:5432/noba'\n"
        "Alembic is only used for PostgreSQL enterprise deployments. "
        "SQLite installs manage their schema automatically at startup."
    )

# ── Alembic config ────────────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No SQLAlchemy target_metadata — we use raw SQL migrations
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without a live connection)."""
    context.configure(
        url=_db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live PostgreSQL connection."""
    from sqlalchemy import create_engine

    engine = create_engine(_db_url)
    with engine.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
