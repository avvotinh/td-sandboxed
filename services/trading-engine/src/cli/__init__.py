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

from .config import config_app
from .main import app

__all__ = ["app", "config_app"]
