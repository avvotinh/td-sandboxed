"""CLI module - Command-line interface for trading engine.

This module provides:
- Main CLI entrypoint
- Account management commands
- Engine control commands
- Configuration management commands

Exports:
- app: Main Typer CLI application
- config_app: Configuration subcommands
"""

from .audit import audit_app
from .config import config_app
from .main import app
from .report import report_app

__all__ = ["app", "audit_app", "config_app", "report_app"]
