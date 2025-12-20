"""CLI constants - Shared constants for CLI commands."""

import typer

STATUS_COLORS: dict[str, str] = {
    "active": typer.colors.GREEN,
    "paused": typer.colors.YELLOW,
    "stopped": typer.colors.RED,
    "error": typer.colors.RED,
    "unknown": typer.colors.WHITE,
}
