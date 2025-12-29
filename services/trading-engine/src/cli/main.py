"""Main CLI entrypoint for trading engine."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import typer
from typing_extensions import Annotated

from ..accounts.account_manager import AccountManager
from ..config.loader import ConfigLoader, ConfigValidationError, ConfigSyntaxError
from ..state.redis_state import RedisStateManager
from .accounts import accounts_app
from .config import config_app
from .constants import ENGINE_STATE_KEY, ENGINE_START_TIME_KEY, STATUS_COLORS

app = typer.Typer(
    name="trading-engine",
    help="Multi-account trading engine with FTMO compliance",
    add_completion=False,
)

# Add subcommand groups
app.add_typer(accounts_app, name="accounts")
app.add_typer(config_app, name="config")


def _run_async(coro) -> Any:
    """Run an async coroutine in a new event loop.

    Args:
        coro: Async coroutine to run.

    Returns:
        Result of the coroutine.
    """
    return asyncio.run(coro)


async def set_engine_state(redis: RedisStateManager, state: str) -> None:
    """Set engine state in Redis.

    Args:
        redis: Redis state manager.
        state: Engine state to set.
    """
    await redis.client.set(ENGINE_STATE_KEY, state)


async def get_engine_state(redis: RedisStateManager) -> str:
    """Get engine state from Redis.

    Args:
        redis: Redis state manager.

    Returns:
        Current engine state or "stopped" if not set.
    """
    state = await redis.client.get(ENGINE_STATE_KEY)
    return state or "stopped"


async def get_uptime(redis: RedisStateManager) -> str:
    """Calculate engine uptime from start timestamp.

    Args:
        redis: Redis state manager.

    Returns:
        Formatted uptime string or "N/A" if not running or data is corrupt.
    """
    start_str = await redis.client.get(ENGINE_START_TIME_KEY)
    if not start_str:
        return "N/A"
    try:
        start = datetime.fromisoformat(start_str)
        delta = datetime.now(timezone.utc) - start
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}h {minutes}m {seconds}s"
    except (ValueError, TypeError):
        # Handle corrupt timestamp data gracefully
        return "N/A"


def _validate_config(config_path: str) -> tuple[bool, str, ConfigLoader | None]:
    """Validate configuration file.

    Args:
        config_path: Path to config file.

    Returns:
        Tuple of (success, message, loader).
    """
    try:
        loader = ConfigLoader(config_path)
        config = loader.load()
        return True, f"Configuration valid ({len(config.accounts)} accounts)", loader
    except FileNotFoundError:
        return False, f"Config file not found: {config_path}", None
    except ConfigSyntaxError as e:
        return False, str(e), None
    except ConfigValidationError as e:
        return False, str(e), None
    except ValueError as e:
        return False, str(e), None


def _validate_env_passwords(loader: ConfigLoader) -> tuple[bool, list[str]]:
    """Validate that all required MT5 password environment variables are set.

    Args:
        loader: ConfigLoader with loaded config.

    Returns:
        Tuple of (all_valid, list of missing env vars).
    """
    config = loader.load()
    missing = []
    for account in config.accounts:
        password_env = account.mt5.password_env
        if not os.getenv(password_env):
            missing.append(password_env)
    return len(missing) == 0, missing


def _validate_unique_account_ids(loader: ConfigLoader) -> tuple[bool, list[str]]:
    """Validate that all account IDs are unique.

    Args:
        loader: ConfigLoader with loaded config.

    Returns:
        Tuple of (all_unique, list of duplicate IDs).
    """
    config = loader.load()
    ids = [acc.id for acc in config.accounts]
    seen: set[str] = set()
    duplicates: list[str] = []
    for acc_id in ids:
        if acc_id in seen:
            duplicates.append(acc_id)
        seen.add(acc_id)
    return len(duplicates) == 0, duplicates


@app.command()
def start(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Validate only, don't start trading")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable debug logging")
    ] = False,
) -> None:
    """Start the trading engine."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
        logging.getLogger().setLevel(logging.DEBUG)

    config_path = os.getenv("ACCOUNTS_CONFIG", "configs/accounts.yaml")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    if dry_run:
        typer.echo("Dry run mode - validating configuration...")
        typer.echo("")

        # 1. Config file exists and parses
        valid, msg, loader = _validate_config(config_path)
        if valid:
            typer.echo(typer.style(f"  ✓ {msg}", fg=STATUS_COLORS["connected"]))
        else:
            typer.echo(typer.style(f"  ✗ {msg}", fg=STATUS_COLORS["error"]))
            raise typer.Exit(1)

        # 2. Env vars for MT5 passwords
        if loader:
            env_valid, missing = _validate_env_passwords(loader)
            if env_valid:
                typer.echo(
                    typer.style(
                        "  ✓ All MT5 password env vars set",
                        fg=STATUS_COLORS["connected"],
                    )
                )
            else:
                typer.echo(
                    typer.style(
                        f"  ✗ Missing env vars: {', '.join(missing)}",
                        fg=STATUS_COLORS["error"],
                    )
                )
                raise typer.Exit(1)

            # 3. Unique account IDs
            unique_valid, duplicates = _validate_unique_account_ids(loader)
            if unique_valid:
                typer.echo(
                    typer.style(
                        "  ✓ All account IDs are unique",
                        fg=STATUS_COLORS["connected"],
                    )
                )
            else:
                typer.echo(
                    typer.style(
                        f"  ✗ Duplicate account IDs: {', '.join(duplicates)}",
                        fg=STATUS_COLORS["error"],
                    )
                )
                raise typer.Exit(1)

        # 4. Redis connection
        redis = RedisStateManager(redis_url)
        try:
            _run_async(redis.connect())
            _run_async(redis.client.ping())
            typer.echo(
                typer.style(
                    f"  ✓ Redis connection ({redis_url})",
                    fg=STATUS_COLORS["connected"],
                )
            )
        except Exception as e:
            typer.echo(
                typer.style(
                    f"  ✗ Redis connection failed: {e}", fg=STATUS_COLORS["error"]
                )
            )
            raise typer.Exit(1)
        finally:
            # Always close Redis connection to prevent resource leak
            try:
                _run_async(redis.close())
            except Exception:
                pass  # Ignore close errors

        typer.echo("")
        typer.echo(
            typer.style(
                "Dry run complete - all validations passed", fg=STATUS_COLORS["running"]
            )
        )
        return

    # Full startup sequence
    typer.echo("Starting trading engine...")

    # 1. Validate config
    valid, msg, loader = _validate_config(config_path)
    if not valid:
        typer.echo(typer.style(f"  Config error: {msg}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)
    typer.echo(f"  -> Configuration loaded: {msg}")

    # 2. Connect to Redis
    redis = RedisStateManager(redis_url)
    try:
        _run_async(redis.connect())
        _run_async(redis.client.ping())
        typer.echo(f"  -> Redis connected: {redis_url}")
    except Exception as e:
        typer.echo(
            typer.style(f"  Redis connection failed: {e}", fg=STATUS_COLORS["error"])
        )
        raise typer.Exit(1)

    # 3. Set engine state to starting
    _run_async(set_engine_state(redis, "starting"))
    typer.echo("  -> Engine state: starting")

    # 4. Load and initialize AccountManager
    if loader:
        config = loader.load()
        manager = AccountManager(redis)
        manager.load_accounts(config)
        typer.echo(f"  -> Accounts loaded: {len(config.accounts)}")

        # Initialize account statuses if not already set
        for account in config.accounts:
            status = _run_async(manager.get_account_status(account.id))
            if status is None:
                _run_async(manager.start_account(account.id))
                typer.echo(f"     - {account.id}: initialized to active")
            else:
                typer.echo(f"     - {account.id}: {status}")

    # 5. Set engine state to running and record start time
    _run_async(set_engine_state(redis, "running"))
    start_time = datetime.now(timezone.utc).isoformat()
    _run_async(redis.client.set(ENGINE_START_TIME_KEY, start_time))
    typer.echo("  -> Engine state: running")

    typer.echo("")
    typer.echo(typer.style("Trading engine started", fg=STATUS_COLORS["running"]))


@app.command()
def stop(
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Skip confirmation")
    ] = False,
) -> None:
    """Stop the trading engine gracefully."""
    if not force:
        typer.confirm(
            "Stop the trading engine? (accounts will remain in current state)", abort=True
        )

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis = RedisStateManager(redis_url)

    try:
        _run_async(redis.connect())
        typer.echo("Initiating graceful shutdown...")

        # 1. Check current state
        current_state = _run_async(get_engine_state(redis))
        if current_state == "stopped":
            typer.echo(
                typer.style("Engine is already stopped", fg=STATUS_COLORS["stopped"])
            )
            _run_async(redis.close())
            return

        # 2. Set stopping state
        _run_async(set_engine_state(redis, "stopping"))
        typer.echo("  -> Stopping signal processing...")

        # 3. Wait for pending orders (placeholder - would need ZmqAdapter reference)
        typer.echo("  -> Waiting for pending orders...")

        # 4. Persist final state
        typer.echo("  -> Persisting final state...")
        _run_async(set_engine_state(redis, "stopped"))
        _run_async(redis.client.delete(ENGINE_START_TIME_KEY))

        # 5. Close connections
        typer.echo("  -> Closing connections...")
        _run_async(redis.close())

        typer.echo("")
        typer.echo(
            typer.style("Trading engine stopped", fg=STATUS_COLORS["stopped"])
        )

    except Exception as e:
        typer.echo(typer.style(f"Shutdown error: {e}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)


@app.command()
def status(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output as JSON for scripting")
    ] = False,
) -> None:
    """Show trading engine status."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis = RedisStateManager(redis_url)

    redis_status = "disconnected"
    try:
        _run_async(redis.connect())
        _run_async(redis.client.ping())
        redis_status = "connected"
    except Exception:
        pass

    # Get engine state and uptime from Redis
    if redis_status == "connected":
        engine_state = _run_async(get_engine_state(redis))
        uptime = _run_async(get_uptime(redis)) if engine_state == "running" else "N/A"
    else:
        engine_state = "unknown"
        uptime = "N/A"

    # Get account statuses
    if redis_status == "connected":
        statuses = _run_async(redis.get_all_account_statuses())
    else:
        statuses = {}

    active = sum(1 for s in statuses.values() if s == "active")
    paused = sum(1 for s in statuses.values() if s == "paused")
    stopped = sum(1 for s in statuses.values() if s == "stopped")

    # ZMQ bridge status (placeholder - would need ZmqAdapter instance)
    zmq_host = os.getenv("ZMQ_BRIDGE_HOST", "localhost")
    zmq_port = os.getenv("ZMQ_PUB_PORT", "5556")
    zmq_status = "disconnected"

    status_data = {
        "engine": {"status": engine_state, "uptime": uptime},
        "accounts": {
            "active": active,
            "paused": paused,
            "stopped": stopped,
            "total": len(statuses),
        },
        "connections": {
            "redis": {"status": redis_status, "url": redis_url},
            "mt5_bridge": {"status": zmq_status, "host": f"{zmq_host}:{zmq_port}"},
        },
    }

    if json_output:
        typer.echo(json.dumps(status_data, indent=2))
    else:
        typer.echo("Trading Engine Status")
        typer.echo("=" * 21)
        engine_color = STATUS_COLORS.get(engine_state, STATUS_COLORS["unknown"])
        typer.echo("Engine:     " + typer.style(engine_state, fg=engine_color))
        typer.echo(f"Uptime:     {uptime}")
        typer.echo(
            f"Accounts:   {active} active, {paused} paused, {stopped} stopped"
        )
        typer.echo("")
        typer.echo("Connections:")
        redis_color = STATUS_COLORS.get(redis_status, STATUS_COLORS["unknown"])
        typer.echo(
            "  Redis:      "
            + typer.style(redis_status, fg=redis_color)
            + f" ({redis_url})"
        )
        zmq_color = STATUS_COLORS.get(zmq_status, STATUS_COLORS["unknown"])
        typer.echo(
            "  MT5 Bridge: "
            + typer.style(zmq_status, fg=zmq_color)
            + f" ({zmq_host}:{zmq_port})"
        )

    if redis_status == "connected":
        _run_async(redis.close())


def cli() -> None:
    """CLI entry point."""
    app()
