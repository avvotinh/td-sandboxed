"""Audit CLI commands - Query audit history from TimescaleDB."""

from __future__ import annotations

import asyncio
import csv
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from tabulate import tabulate
from typing_extensions import Annotated

from .constants import STATUS_COLORS

audit_app = typer.Typer(
    name="audit",
    help="Query audit history and compliance data from TimescaleDB",
    add_completion=False,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_async(coro: Any) -> Any:
    """Run an async coroutine in a new event loop.

    Note: Duplicated from main.py to avoid circular import
    (main.py imports audit_app from this module).
    """
    return asyncio.run(coro)


def _get_db_session_factory() -> Any:
    """Create async DB session factory from DATABASE_URL.

    Returns an async_sessionmaker or raises typer.Exit(1) on failure.
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        typer.echo(
            typer.style(
                "Database connection required. Set DATABASE_URL environment variable.",
                fg=STATUS_COLORS["error"],
            )
        )
        raise typer.Exit(1)

    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


async def _query_trades(
    session: Any,
    account_id: str,
    since: datetime,
    until: datetime | None = None,
    symbol: str | None = None,
    limit: int = 100,
) -> list[Any]:
    """Query trades from TimescaleDB."""
    from sqlalchemy import select

    from ..orders.db_models import TradeRecord

    stmt = select(TradeRecord).where(
        TradeRecord.account_id == account_id,
        TradeRecord.entry_time >= since,
    )
    if until is not None:
        stmt = stmt.where(TradeRecord.entry_time < until)
    if symbol is not None:
        stmt = stmt.where(TradeRecord.symbol == symbol)
    stmt = stmt.order_by(TradeRecord.entry_time.desc()).limit(limit)

    result = await session.scalars(stmt)
    return result.all()


async def _query_violations(
    session: Any,
    account_id: str,
    since: datetime,
    rule_type: str | None = None,
    limit: int = 100,
) -> list[Any]:
    """Query rule violations from TimescaleDB."""
    from sqlalchemy import select

    from ..rules.violation_db_writer import RuleViolationModel

    stmt = (
        select(RuleViolationModel)
        .where(
            RuleViolationModel.account_id == account_id,
            RuleViolationModel.timestamp >= since,
        )
        .order_by(RuleViolationModel.timestamp.desc())
        .limit(limit)
    )
    if rule_type is not None:
        stmt = stmt.where(RuleViolationModel.rule_type == rule_type)

    result = await session.scalars(stmt)
    return result.all()


async def _query_snapshots(
    session: Any,
    account_id: str,
    since_date: date | None = None,
    until_date: date | None = None,
    limit: int = 100,
) -> list[Any]:
    """Query account snapshots from TimescaleDB."""
    from sqlalchemy import select

    from ..snapshots.models import AccountSnapshotModel

    stmt = select(AccountSnapshotModel).where(
        AccountSnapshotModel.account_id == account_id,
    )
    if since_date is not None:
        stmt = stmt.where(AccountSnapshotModel.snapshot_date >= since_date)
    if until_date is not None:
        stmt = stmt.where(AccountSnapshotModel.snapshot_date <= until_date)
    stmt = stmt.order_by(AccountSnapshotModel.snapshot_date.desc()).limit(limit)

    result = await session.scalars(stmt)
    return result.all()


def _compute_trade_summary(trades: list[Any]) -> dict[str, Any]:
    """Compute trade summary statistics.

    Args:
        trades: List of TradeRecord instances.

    Returns:
        Dict with total_trades, net_pnl, winning, losing, win_rate.
    """
    total = len(trades)
    net_pnl = Decimal("0")
    winning = 0
    losing = 0

    for t in trades:
        if t.pnl_dollars is not None:
            net_pnl += t.pnl_dollars
            if t.pnl_dollars > 0:
                winning += 1
            elif t.pnl_dollars < 0:
                losing += 1

    closed = winning + losing
    win_rate = round((winning / closed) * 100, 2) if closed > 0 else 0.0

    return {
        "total_trades": total,
        "net_pnl": net_pnl,
        "winning": winning,
        "losing": losing,
        "win_rate": win_rate,
    }


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def _format_pnl(value: Decimal | None) -> str:
    """Format P&L value with sign and color."""
    if value is None:
        return "-"
    formatted = f"${value:+,.2f}"
    if value > 0:
        return typer.style(formatted, fg=STATUS_COLORS["connected"])
    elif value < 0:
        return typer.style(formatted, fg=STATUS_COLORS["error"])
    return formatted


def _format_pnl_plain(value: Decimal | None) -> str:
    """Format P&L value without color for CSV/JSON."""
    if value is None:
        return "-"
    return f"${value:+,.2f}"


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------


def _export_json(records: list[Any], output_file: str | None = None) -> str:
    """Serialize records to JSON. Financial fields preserved as strings via to_dict()."""
    data = [r.to_dict() for r in records]
    json_str = json.dumps(data, indent=2, default=str)

    if output_file:
        Path(output_file).write_text(json_str)
    return json_str


def _export_csv(
    records: list[Any],
    headers: list[str],
    row_func: Any,
    command: str,
    account_id: str,
) -> str:
    """Export records to CSV file.

    Returns the filename written.
    """
    today = date.today().isoformat()
    filename = f"{command}-{account_id}-{today}.csv"

    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for record in records:
            writer.writerow(row_func(record))

    return filename


def _trade_csv_row(t: Any) -> list[str]:
    """Convert a trade record to a CSV row."""
    return [
        t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else "",
        t.symbol,
        t.side,
        str(t.quantity),
        str(t.entry_price),
        str(t.exit_price) if t.exit_price is not None else "OPEN",
        str(t.pnl_dollars) if t.pnl_dollars is not None else "",
        t.strategy_name,
    ]


def _violation_csv_row(v: Any) -> list[str]:
    """Convert a violation record to a CSV row."""
    return [
        v.timestamp.strftime("%Y-%m-%d %H:%M") if v.timestamp else "",
        v.rule_type,
        v.severity,
        str(v.current_value) if v.current_value is not None else "",
        str(v.threshold_value) if v.threshold_value is not None else "",
        v.action_taken,
        v.message or "",
    ]


def _snapshot_csv_row(s: Any) -> list[str]:
    """Convert a snapshot record to a CSV row."""
    return [
        s.snapshot_date.isoformat() if s.snapshot_date else "",
        str(s.opening_balance) if s.opening_balance is not None else "",
        str(s.closing_balance) if s.closing_balance is not None else "",
        str(s.high_balance) if s.high_balance is not None else "",
        str(s.low_balance) if s.low_balance is not None else "",
        str(s.daily_pnl) if s.daily_pnl is not None else "",
        str(s.daily_pnl_percent) if s.daily_pnl_percent is not None else "",
        str(s.drawdown_percent) if s.drawdown_percent is not None else "",
        str(s.trades_count),
        f"{s.winning_trades}/{s.losing_trades}",
    ]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@audit_app.command()
def trades(
    account: Annotated[str, typer.Option("--account", "-a", help="Account ID")],
    days: Annotated[int, typer.Option("--days", "-d", help="Days to look back")] = 7,
    symbol: Annotated[str | None, typer.Option("--symbol", "-s", help="Filter by symbol")] = None,
    since: Annotated[str | None, typer.Option("--since", help="Start datetime (ISO format), overrides --days")] = None,
    until: Annotated[str | None, typer.Option("--until", help="End datetime (ISO format)")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output")] = False,
    export: Annotated[str | None, typer.Option("--export", help='Export format ("csv")')] = None,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max entries")] = 100,
) -> None:
    """Query trade history for an account."""
    session_factory = _get_db_session_factory()

    # Parse time range
    if since is not None:
        since_dt = datetime.fromisoformat(since)
        if since_dt.tzinfo is None:
            since_dt = since_dt.replace(tzinfo=timezone.utc)
    else:
        since_dt = datetime.now(timezone.utc) - timedelta(days=days)

    until_dt = None
    if until is not None:
        until_dt = datetime.fromisoformat(until)
        if until_dt.tzinfo is None:
            until_dt = until_dt.replace(tzinfo=timezone.utc)

    async def _run() -> list[Any]:
        async with session_factory() as session:
            return await _query_trades(session, account, since_dt, until_dt, symbol, limit)

    records = _run_async(_run())

    # Handle empty results
    if not records:
        typer.echo(f"No trades found for {account} in the specified time range.")
        return

    # JSON output
    if json_output:
        typer.echo(_export_json(records))
        return

    # CSV export
    if export and export.lower() == "csv":
        csv_headers = ["Date", "Symbol", "Side", "Size", "Entry", "Exit", "P&L", "Strategy"]
        filename = _export_csv(records, csv_headers, _trade_csv_row, "trades", account)
        typer.echo(f"Exported {len(records)} records to {filename}")
        return

    # Table output
    summary = _compute_trade_summary(records)

    if since is not None:
        typer.echo(f"Trades for {account} (since {since})")
    else:
        typer.echo(f"Trades for {account} (last {days} days)")
    typer.echo("=" * 50)

    rows = []
    for t in records:
        pnl_str = _format_pnl(t.pnl_dollars) if t.pnl_dollars is not None else "-"

        rows.append([
            t.entry_time.strftime("%Y-%m-%d") if t.entry_time else "",
            t.symbol,
            t.side,
            str(t.quantity),
            f"${t.entry_price:,.2f}" if t.entry_price is not None else "-",
            f"${t.exit_price:,.2f}" if t.exit_price is not None else "OPEN",
            pnl_str,
            t.strategy_name,
        ])

    headers = ["Date", "Symbol", "Side", "Size", "Entry", "Exit", "P&L", "Strategy"]
    typer.echo(tabulate(rows, headers=headers, tablefmt="simple"))
    typer.echo("")
    net_pnl_str = _format_pnl(summary["net_pnl"])
    typer.echo(
        f"Total: {summary['total_trades']} trades | Net P&L: {net_pnl_str} | "
        f"Win Rate: {summary['win_rate']:.1f}%"
    )


@audit_app.command()
def violations(
    account: Annotated[str, typer.Option("--account", "-a", help="Account ID")],
    days: Annotated[int, typer.Option("--days", "-d", help="Days to look back")] = 30,
    rule_type: Annotated[str | None, typer.Option("--rule-type", "-r", help="Filter by rule type")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output")] = False,
    export: Annotated[str | None, typer.Option("--export", help='Export format ("csv")')] = None,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max entries")] = 100,
) -> None:
    """Query rule violations for an account."""
    session_factory = _get_db_session_factory()

    since_dt = datetime.now(timezone.utc) - timedelta(days=days)

    async def _run() -> list[Any]:
        async with session_factory() as session:
            return await _query_violations(session, account, since_dt, rule_type, limit)

    records = _run_async(_run())

    if not records:
        typer.echo(f"No violations found for {account} in the specified time range.")
        return

    # JSON output
    if json_output:
        typer.echo(_export_json(records))
        return

    # CSV export
    if export and export.lower() == "csv":
        csv_headers = ["Date", "Rule", "Severity", "Value", "Limit", "Action", "Message"]
        filename = _export_csv(records, csv_headers, _violation_csv_row, "violations", account)
        typer.echo(f"Exported {len(records)} records to {filename}")
        return

    # Table output
    typer.echo(f"Rule Violations for {account} (last {days} days)")
    typer.echo("=" * 50)

    rows = []
    blocked_count = 0
    rule_counts: dict[str, int] = {}

    for v in records:
        # Color severity
        sev = v.severity
        if sev in ("CRITICAL", "FATAL"):
            sev_styled = typer.style(sev, fg=STATUS_COLORS["error"])
        elif sev == "WARNING":
            sev_styled = typer.style(sev, fg=STATUS_COLORS["paused"])
        else:
            sev_styled = sev

        # Color action
        action = v.action_taken
        if action == "blocked":
            action_styled = typer.style(action, fg=STATUS_COLORS["error"])
            blocked_count += 1
        elif action == "warned":
            action_styled = typer.style(action, fg=STATUS_COLORS["paused"])
        else:
            action_styled = action

        # Track most triggered rule
        rule_counts[v.rule_type] = rule_counts.get(v.rule_type, 0) + 1

        # Format values with appropriate precision
        val_str = f"{v.current_value:.4f}" if v.current_value is not None else "-"
        lim_str = f"{v.threshold_value:.4f}" if v.threshold_value is not None else "-"

        rows.append([
            v.timestamp.strftime("%Y-%m-%d") if v.timestamp else "",
            v.rule_type,
            sev_styled,
            val_str,
            lim_str,
            action_styled,
            (v.message[:40] + "..." if v.message and len(v.message) > 40 else v.message) or "",
        ])

    headers = ["Date", "Rule", "Severity", "Value", "Limit", "Action", "Message"]
    typer.echo(tabulate(rows, headers=headers, tablefmt="simple"))
    typer.echo("")

    most_triggered = max(rule_counts, key=rule_counts.get) if rule_counts else "N/A"
    typer.echo(
        f"Total: {len(records)} violations | Blocks: {blocked_count} | "
        f"Most triggered: {most_triggered}"
    )


@audit_app.command()
def daily(
    account: Annotated[str, typer.Option("--account", "-a", help="Account ID")],
    days: Annotated[int | None, typer.Option("--days", "-d", help="Number of days to show")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output")] = False,
    export: Annotated[str | None, typer.Option("--export", help='Export format ("csv")')] = None,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max entries")] = 100,
) -> None:
    """Query daily account snapshots."""
    session_factory = _get_db_session_factory()

    since_date = None
    if days is not None:
        since_date = (datetime.now(timezone.utc) - timedelta(days=days)).date()

    async def _run() -> list[Any]:
        async with session_factory() as session:
            return await _query_snapshots(session, account, since_date, None, limit)

    records = _run_async(_run())

    if not records:
        typer.echo(f"No snapshots found for {account}.")
        return

    # JSON output
    if json_output:
        typer.echo(_export_json(records))
        return

    # CSV export
    if export and export.lower() == "csv":
        csv_headers = ["Date", "Open", "Close", "High", "Low", "P&L", "P&L%", "DD%", "Trades", "W/L"]
        filename = _export_csv(records, csv_headers, _snapshot_csv_row, "daily", account)
        typer.echo(f"Exported {len(records)} records to {filename}")
        return

    # Table output
    days_label = f" (last {days} days)" if days else ""
    typer.echo(f"Daily Snapshots for {account}{days_label}")
    typer.echo("=" * 50)

    rows = []
    pnl_values: list[Decimal] = []
    trading_days = 0

    for s in records:
        pnl_str = _format_pnl(s.daily_pnl)
        pnl_pct = f"{s.daily_pnl_percent:.2f}%" if s.daily_pnl_percent is not None else "-"
        dd_pct = f"{s.drawdown_percent:.2f}%" if s.drawdown_percent is not None else "-"
        wl = f"{s.winning_trades}/{s.losing_trades}"

        if s.daily_pnl is not None:
            pnl_values.append(s.daily_pnl)
        if s.trades_count and s.trades_count > 0:
            trading_days += 1

        rows.append([
            s.snapshot_date.isoformat() if s.snapshot_date else "",
            f"${s.opening_balance:,.2f}" if s.opening_balance is not None else "-",
            f"${s.closing_balance:,.2f}" if s.closing_balance is not None else "-",
            f"${s.high_balance:,.2f}" if s.high_balance is not None else "-",
            f"${s.low_balance:,.2f}" if s.low_balance is not None else "-",
            pnl_str,
            pnl_pct,
            dd_pct,
            str(s.trades_count),
            wl,
        ])

    headers = ["Date", "Open", "Close", "High", "Low", "P&L", "P&L%", "DD%", "Trades", "W/L"]
    typer.echo(tabulate(rows, headers=headers, tablefmt="simple"))
    typer.echo("")

    if pnl_values:
        best = max(pnl_values)
        worst = min(pnl_values)
        total = sum(pnl_values)
        typer.echo(
            f"Trading Days: {trading_days} | Best Day: {_format_pnl(best)} | "
            f"Worst Day: {_format_pnl(worst)} | Net P&L: {_format_pnl(total)}"
        )
    else:
        typer.echo(f"Trading Days: {trading_days}")
