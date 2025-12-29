"""CLI constants - Shared constants for CLI commands."""

import typer

STATUS_COLORS: dict[str, str] = {
    "active": typer.colors.GREEN,
    "running": typer.colors.GREEN,
    "paused": typer.colors.YELLOW,
    "starting": typer.colors.CYAN,
    "stopping": typer.colors.YELLOW,
    "stopped": typer.colors.RED,
    "error": typer.colors.RED,
    "unknown": typer.colors.WHITE,
    "connected": typer.colors.GREEN,
    "disconnected": typer.colors.RED,
}

# Redis key patterns for engine state
ENGINE_STATE_KEY = "engine:state"
ENGINE_START_TIME_KEY = "engine:start_time"
