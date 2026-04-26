"""CLI commands for account management."""

import asyncio
import os
import uuid
from typing import Any

import typer
from sqlalchemy.exc import SQLAlchemyError
from tabulate import tabulate

from ..accounts.account_manager import AccountManager
from ..accounts.metrics_service import AccountMetricsService
from ..accounts.phase_promotion import (
    PhasePromotionError,
    build_phase_transition_audit_entry,
    validate_phase_transition,
)
from ..accounts.risk_registry import RiskStateRegistry
from ..config.firm_registry import FirmRegistry, FirmRegistryError
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


def _get_metrics_service(
    redis: RedisStateManager, manager: AccountManager
) -> AccountMetricsService:
    """Create AccountMetricsService with dependencies.

    Args:
        redis: Redis state manager.
        manager: Account manager.

    Returns:
        Configured AccountMetricsService instance.
    """
    risk_registry = RiskStateRegistry(redis)
    manager.set_risk_registry(risk_registry)
    return AccountMetricsService(redis, risk_registry, manager)


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


@accounts_app.command("add")
def add_account(
    account_id: str = typer.Argument(..., help="Account ID to add from config"),
) -> None:
    """Hot-reload: Add a new account while engine is running.

    The account must already be defined in accounts.yaml.
    This command loads the account and starts it if status is 'active'.
    """
    try:
        manager = _get_account_manager()
        # Reload config to get the fresh account definition
        config_path = os.getenv("ACCOUNTS_CONFIG", "configs/accounts.yaml")
        loader = ConfigLoader(config_path)
        fresh_config = loader.load()

        _run_async(manager.add_account(account_id, fresh_config))
        typer.echo(
            typer.style(f"✓ Account {account_id} added and started", fg=STATUS_COLORS["active"])
        )
        _run_async(manager.close())
    except ValueError as e:
        typer.echo(typer.style(f"✗ Error: {e}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)


@accounts_app.command("status")
def account_status(
    account_id: str = typer.Argument(..., help="Account ID to show status for"),
) -> None:
    """Show detailed status for a specific account.

    Displays Account ID, Name, Status, Balance, Equity, Daily P&L,
    Max Drawdown, and Peak Equity from the account's metrics.

    Example: trading-engine accounts status ftmo-gold-001
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

    # Load accounts config
    config_path = os.getenv("ACCOUNTS_CONFIG", "configs/accounts.yaml")
    try:
        loader = ConfigLoader(config_path)
        accounts_config = loader.load()
    except FileNotFoundError:
        typer.echo(
            typer.style(
                f"✗ Config file not found: {config_path}",
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
    metrics_service = _get_metrics_service(redis, manager)

    # Get account metrics
    metrics = _run_async(metrics_service.get_account_metrics(account_id))

    if not metrics:
        typer.echo(
            typer.style(f"Account not found: {account_id}", fg=STATUS_COLORS["error"])
        )
        _run_async(redis.close())
        raise typer.Exit(1)

    # Display formatted output
    status_data = metrics.to_status_dict()
    status_color = STATUS_COLORS.get(metrics.status, STATUS_COLORS["unknown"])

    typer.echo(f"Account: {status_data['account_id']} ({status_data['account_name']})")
    typer.echo("Status: " + typer.style(status_data["status"], fg=status_color))
    typer.echo(f"Balance: {status_data['balance']}")
    typer.echo(f"Equity: {status_data['equity']}")

    # Color-code P&L
    pnl_color = STATUS_COLORS.get("active") if metrics.daily_pnl >= 0 else STATUS_COLORS.get("error")
    typer.echo("Daily P&L: " + typer.style(status_data["daily_pnl"], fg=pnl_color))

    typer.echo(f"Max Drawdown: {status_data['max_drawdown']}")
    typer.echo(f"Peak Equity: {status_data['peak_equity']}")

    _run_async(redis.close())


@accounts_app.command("list")
def list_accounts() -> None:
    """List all accounts with summary metrics.

    Displays a table with columns: ID, Name, Status, Balance, Daily P&L %
    Sorted by status (active first), then by ID.
    Shows total balance across all accounts.

    Example: trading-engine accounts list
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

    # Load accounts config
    config_path = os.getenv("ACCOUNTS_CONFIG", "configs/accounts.yaml")
    try:
        loader = ConfigLoader(config_path)
        accounts_config = loader.load()
    except FileNotFoundError:
        typer.echo(
            typer.style(
                f"✗ Config file not found: {config_path}",
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
    metrics_service = _get_metrics_service(redis, manager)

    # Get all account metrics
    all_metrics = _run_async(metrics_service.get_all_account_metrics())

    if not all_metrics:
        typer.echo("No accounts configured.")
        _run_async(redis.close())
        return

    # Sort: active first, then by ID
    sorted_metrics = sorted(
        all_metrics.values(),
        key=lambda m: (0 if m.status == "active" else 1, m.account_id),
    )

    # Build table
    headers = ["ID", "Name", "Status", "Balance", "Daily P&L"]
    rows = [m.to_list_row() for m in sorted_metrics]

    typer.echo(tabulate(rows, headers=headers, tablefmt="simple"))

    # Summary row
    total_balance = sum(m.balance for m in sorted_metrics)
    typer.echo(f"\nTotal Balance: ${total_balance:,.2f}")

    _run_async(redis.close())


# ---------------------------------------------------------------------------
# Epic 9 P0.10 — manual phase promotion
# ---------------------------------------------------------------------------


def _load_accounts_config_or_exit():
    """Load accounts.yaml or exit 1 with a clear message. No Redis required."""
    config_path = os.getenv("ACCOUNTS_CONFIG", "configs/accounts.yaml")
    try:
        return ConfigLoader(config_path).load(), config_path
    except FileNotFoundError:
        typer.echo(
            typer.style(
                f"✗ Config file not found: {config_path}",
                fg=STATUS_COLORS["error"],
            )
        )
        raise typer.Exit(1)
    except ConfigValidationError as e:
        typer.echo(typer.style(f"✗ {e}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)


def _load_firm_registry_or_exit(firms_dir: str) -> FirmRegistry:
    registry = FirmRegistry(firms_dir=firms_dir)
    try:
        registry.load()
    except FirmRegistryError as e:
        typer.echo(typer.style(f"✗ FirmRegistry: {e}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)
    return registry


async def _persist_audit_entry(session_factory, entry) -> None:
    """Insert a single AuditEntry directly. Used for one-shot CLI writes."""
    from ..rules.audit_db_writer import AuditLogModel

    async with session_factory() as session:
        async with session.begin():
            session.add(AuditLogModel.from_audit_entry(entry))


@accounts_app.command("promote")
def promote_account(
    account_id: str = typer.Option(..., "--account", help="Account ID to promote"),
    target_phase: str = typer.Option(..., "--phase", help="Target phase id (e.g. verification, funded)"),
    reason: str = typer.Option(..., "--reason", "-r", help="Reason for the transition (required for compliance audit)"),
    actor: str = typer.Option(
        "",
        "--actor",
        help="Operator initiating the change (defaults to $USER)",
    ),
    firms_dir: str = typer.Option(
        "",
        "--firms-dir",
        help="Directory holding firm YAML profiles "
             "(defaults to $FIRMS_DIR or 'configs/firms' relative to CWD)",
    ),
) -> None:
    """Promote a firm-bound account between phases (Epic 9 P0.10).

    Validates the transition against the firm's product profile, writes
    a phase_transition audit row (with a fresh correlation_id), and
    prompts the operator to update accounts.yaml + restart the engine
    for the change to take effect. Does NOT mutate accounts.yaml — the
    audit row is the canonical record.

    The command resolves config paths relative to the current working
    directory; either run from the repo root or set $ACCOUNTS_CONFIG /
    $FIRMS_DIR environment variables.

    Example:

        trading-engine accounts promote \\
            --account ftmo-001 \\
            --phase verification \\
            --reason "Passed Challenge target on 2026-04-15"
    """
    if not actor:
        actor = os.getenv("USER", "unknown")
    if not firms_dir:
        firms_dir = os.getenv("FIRMS_DIR", "configs/firms")

    accounts_config, config_path = _load_accounts_config_or_exit()
    account = next(
        (a for a in accounts_config.accounts if a.id == account_id), None,
    )
    if account is None:
        typer.echo(
            typer.style(
                f"✗ Account {account_id!r} not found in {config_path}",
                fg=STATUS_COLORS["error"],
            )
        )
        raise typer.Exit(1)

    registry = _load_firm_registry_or_exit(firms_dir)

    correlation_id = str(uuid.uuid4())
    try:
        from_phase, to_phase = validate_phase_transition(
            account, registry, target_phase,
        )
        entry = build_phase_transition_audit_entry(
            account=account,
            from_phase=from_phase,
            to_phase=to_phase,
            reason=reason,
            actor=actor,
            correlation_id=correlation_id,
        )
    except PhasePromotionError as e:
        typer.echo(typer.style(f"✗ {e}", fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)

    # Persist the audit entry. Reuses the audit CLI's session factory
    # (public alias) so DATABASE_URL handling stays in one place.
    from .audit import get_db_session_factory

    session_factory = get_db_session_factory()
    try:
        _run_async(_persist_audit_entry(session_factory, entry))
    except (OSError, SQLAlchemyError) as e:
        typer.echo(
            typer.style(
                f"✗ Failed to write audit entry: {e}",
                fg=STATUS_COLORS["error"],
            )
        )
        raise typer.Exit(1)

    typer.echo(
        typer.style(
            f"✓ Phase transition recorded for {account_id}: "
            f"{from_phase.phase_id} → {to_phase.phase_id}",
            fg=STATUS_COLORS["active"],
        )
    )
    typer.echo(f"  Reason:         {reason}")
    typer.echo(f"  Actor:          {actor}")
    typer.echo(f"  Correlation ID: {correlation_id}")
    typer.echo(
        typer.style(
            f"\n  NOTE: edit {config_path} and set `phase: {to_phase.phase_id}` "
            f"for account {account_id}, then restart the engine to make "
            "the change effective.",
            fg=STATUS_COLORS["paused"],
        )
    )
