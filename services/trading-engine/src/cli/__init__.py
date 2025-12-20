"""CLI module - Command-line interface for trading engine.

This module provides:
- Main CLI entrypoint
- Account management commands
- Engine control commands

Exports:
- app: Main Typer CLI application
"""

from .main import app

__all__ = ["app"]
