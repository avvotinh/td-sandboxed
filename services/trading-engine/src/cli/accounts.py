"""CLI commands for account management."""

import asyncio
import os
from typing import Any, Optional

import typer

from ..accounts.account_manager import AccountManager
from ..config.loader import ConfigLoader, ConfigValidationError
from ..state.redis_state import RedisStateManager
from .constants import STATUS_COLORS

accounts_app = typer.Typer(help="Manage trading accounts")


def _run_async(coro) -> Any:
    """Run an async coroutine in a new event loop.

    Args:
        coro: Async coroutine to run.

    Returns:
        Result of the coroutine.
    """
    return asyncio.run(coro)


def _get_account_manager() -> AccountManager:
    """Get configured AccountManager with Redis connection.

    Returns:
        Configured AccountManager instance.

    Raises:
        typer.Exit: If configuration fails.
    """
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis = RedisStateManager(redis_url)

    try:
        _run_async(redis.connect())
    except Exception as e:
        typer.echo(
            typer.style(f"✗ Redis connection failed: {e}", fg=STATUS_COLORS["error"])
        )
        raise typer.Exit(1)

    # Load accounts config to validate account IDs
    config_path = os.getenv("ACCOUNTS_CONFIG", "configs/accounts.yaml")
    try:
        loader = ConfigLoader(config_path)
        accounts_config = loader.load()
    except FileNotFoundError:
        typer.echo(
            typer.style(
                f"✗ Config file not found: {config_path}\n"
                "  Set ACCOUNTS_CONFIG environment variable or create configs/accounts.yaml",
                fg=STATUS_COLORS["error"],
            )
        )
        _run_async(redis.close())
        raise typer.Exit(1)
    except ConfigValidationError as e:
        typer.echo(typer.style(f"✗ {e}", fg=STATUS_COLORS["error"]))
        _run_async(redis.close())
        raise typer.Exit(1)

    manager = AccountManager(redis)
    manager.load_accounts(accounts_config)
    return manager


@accounts_app.command("start")
def start_account(
    account_id: str = typer.Argument(..., help="Account ID to start"),
) -> None:
    """Start a trading account (from stopped or new state)."""
    try:
        manager = _get_account_manager()
        _run_async(manager.start_account(account_id))
        typer.echo(
            typer.style(f"✓ Account {account_id} started", fg=STATUS_COLORS["active"])
        )
        _run_async(manager.close())
    except ValueError as e:
        typer.echo(typer.style(f"✗ Error: {e}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)


@accounts_app.command("stop")
def stop_account(
    account_id: str = typer.Argument(..., help="Account ID to stop"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Stop a trading account (positions remain open)."""
    if not force:
        typer.confirm(
            f"Stop account {account_id}? Positions will remain open.",
            abort=True,
        )
    try:
        manager = _get_account_manager()
        _run_async(manager.stop_account(account_id))
        typer.echo(
            typer.style(f"✓ Account {account_id} stopped", fg=STATUS_COLORS["stopped"])
        )
        _run_async(manager.close())
    except ValueError as e:
        typer.echo(typer.style(f"✗ Error: {e}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)


@accounts_app.command("pause")
def pause_account(
    account_id: str = typer.Argument(..., help="Account ID to pause"),
) -> None:
    """Pause a trading account temporarily."""
    try:
        manager = _get_account_manager()
        _run_async(manager.pause_account(account_id))
        typer.echo(
            typer.style(f"✓ Account {account_id} paused", fg=STATUS_COLORS["paused"])
        )
        _run_async(manager.close())
    except ValueError as e:
        typer.echo(typer.style(f"✗ Error: {e}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)


@accounts_app.command("resume")
def resume_account(
    account_id: str = typer.Argument(..., help="Account ID to resume"),
) -> None:
    """Resume a paused trading account."""
    try:
        manager = _get_account_manager()
        _run_async(manager.resume_account(account_id))
        typer.echo(
            typer.style(f"✓ Account {account_id} resumed", fg=STATUS_COLORS["active"])
        )
        _run_async(manager.close())
    except ValueError as e:
        typer.echo(typer.style(f"✗ Error: {e}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)


@accounts_app.command("status")
def account_status(
    account_id: Optional[str] = typer.Argument(None, help="Account ID (optional)"),
) -> None:
    """Show account status (all accounts if no ID specified)."""
    try:
        manager = _get_account_manager()
        if account_id:
            # Validate account exists
            try:
                manager._validate_account_exists(account_id)
            except ValueError as e:
                typer.echo(typer.style(f"✗ Error: {e}", fg=STATUS_COLORS["error"]))
                _run_async(manager.close())
                raise typer.Exit(1)

            status = _run_async(manager.get_account_status(account_id)) or "unknown"
            color = STATUS_COLORS.get(status, STATUS_COLORS["unknown"])
            typer.echo(f"Account {account_id}: " + typer.style(status, fg=color))
        else:
            statuses = _run_async(manager.get_all_statuses())
            if not statuses:
                typer.echo("No accounts configured.")
            else:
                typer.echo("Account Statuses:")
                for acc_id, status in statuses.items():
                    color = STATUS_COLORS.get(status, STATUS_COLORS["unknown"])
                    typer.echo(f"  {acc_id}: " + typer.style(status, fg=color))
        _run_async(manager.close())
    except ValueError as e:
        typer.echo(typer.style(f"✗ Error: {e}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)
