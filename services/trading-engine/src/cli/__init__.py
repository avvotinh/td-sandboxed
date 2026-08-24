"""CLI module - Command-line interface for trading engine.

This module provides:
- Main CLI entrypoint (backtest, audit, report)

The account-management and config groups were removed with ``src/accounts/``
(P3.2); live-session control returns at P5.

Exports:
- app: Main Typer CLI application
"""

from .audit import audit_app
from .main import app
from .report import report_app

__all__ = ["app", "audit_app", "report_app"]
