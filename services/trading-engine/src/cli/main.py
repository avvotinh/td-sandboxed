"""Trading engine CLI.

v2 is a single-account system driven from the research loop, so this is a thin
launcher for the sub-apps rather than a control plane. The multi-account engine
commands (``start``/``stop``/``status``/``logs``) and the ``accounts``/``config``
groups were removed with ``src/accounts/`` — they drove a multi-account
orchestrator over Redis that no longer exists (docs/v2/decisions.md D3).

Live-session control returns at P5 as ``src/live/session.py``, scoped to one
account.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import typer

from src.lab.cli import backtest_app

from .audit import audit_app
from .report import report_app

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def create_db_session_factory() -> "async_sessionmaker[AsyncSession] | None":
    """Create an async session factory from ``DATABASE_URL``, or ``None``.

    Only the live path touches the database; the research loop runs entirely on
    parquet + JSON files (decision D6), so a missing URL is not an error.
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logging.debug("DATABASE_URL not set, database features disabled")
        return None

    try:
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        # Ensure URL uses asyncpg driver
        if database_url.startswith("postgresql://"):
            database_url = database_url.replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )

        async_engine = create_async_engine(database_url, echo=False)
        session_factory = async_sessionmaker(
            async_engine, class_=AsyncSession, expire_on_commit=False
        )
        logging.debug("Database session factory created successfully")
        return session_factory
    except ImportError:
        logging.warning(
            "sqlalchemy[asyncio] not installed, database features disabled"
        )
        return None
    except Exception as e:
        logging.warning("Failed to create database session factory: %s", e)
        return None


app = typer.Typer(
    name="trading-engine",
    help="Single-account trading engine — backtest, audit and report tooling",
    add_completion=False,
)

app.add_typer(backtest_app, name="backtest")
app.add_typer(audit_app, name="audit")
app.add_typer(report_app, name="report")


if __name__ == "__main__":
    app()
