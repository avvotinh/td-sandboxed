"""Alembic runtime — Sandboxed trading engine.

Story 10.10. Two responsibilities:

1. Resolve the connection URL at runtime — alembic.ini intentionally
   leaves ``sqlalchemy.url`` blank so the URL is read from
   ``DATABASE_URL``. ``settings.get_secret`` would also work but
   keeps tests free of pydantic-settings imports.
2. Run migrations. Autogenerate is disabled (every revision is
   hand-written for TimescaleDB DDL), so ``target_metadata`` is
   ``None`` — the offline / online runners only execute
   ``op.execute(...)`` calls inside each revision.
"""
from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

# Alembic Config object — gives access to alembic.ini values.
config = context.config


def _resolve_database_url() -> str:
    """Pick the connection URL: env var first, alembic.ini second."""
    url = os.environ.get("DATABASE_URL")
    if url:
        # The shared application URL uses ``postgresql+asyncpg://`` for
        # the engine's async pool. Alembic runs synchronously, so coerce
        # to the standard ``postgresql://`` driver. ``psycopg2-binary``
        # is included as a dependency for this reason.
        if url.startswith("postgresql+asyncpg://"):
            url = "postgresql://" + url.split("://", 1)[1]
        return url
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url
    raise RuntimeError(
        "Cannot resolve DATABASE_URL — set the env var or alembic.ini "
        "sqlalchemy.url before running alembic."
    )


# Hand-written revisions only: no metadata target.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emits SQL to stdout."""
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connects to the live DB."""
    cfg = config.get_section(config.config_ini_section, {}) or {}
    cfg["sqlalchemy.url"] = _resolve_database_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
