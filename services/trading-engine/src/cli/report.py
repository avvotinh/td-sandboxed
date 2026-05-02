"""Report CLI commands - Generate compliance reports for prop firm accounts."""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import typer
from typing_extensions import Annotated

from .constants import STATUS_COLORS

report_app = typer.Typer(
    name="report",
    help="Generate compliance reports for prop firm accounts",
    add_completion=False,
    invoke_without_command=True,
)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine in a new event loop.

    Note: duplicated from main.py to avoid circular import (main.py imports report_app).
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


@report_app.callback()
def generate(
    account: Annotated[str, typer.Option("--account", "-a", help="Account ID")],
    format: Annotated[str, typer.Option("--format", "-f", help="Output format: pdf, json, csv")] = "pdf",
    days: Annotated[int | None, typer.Option("--days", "-d", help="Number of days to include")] = None,
    since: Annotated[str | None, typer.Option("--since", help="Start date (ISO format), overrides --days")] = None,
    until: Annotated[str | None, typer.Option("--until", help="End date (ISO format, default: today)")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output file path")] = None,
    compare_dashboard: Annotated[bool, typer.Option("--compare-dashboard", help="Show dashboard comparison")] = False,
) -> None:
    """Generate compliance report for a prop firm account."""
    session_factory = _get_db_session_factory()

    # Parse date range
    since_date: date | None = None
    until_date: date | None = None

    if since is not None:
        since_date = date.fromisoformat(since)
    elif days is not None:
        since_date = (datetime.now(timezone.utc) - timedelta(days=days)).date()

    if until is not None:
        until_date = date.fromisoformat(until)

    # Gather report data
    from ..reports.data_gatherer import ReportDataGatherer

    gatherer = ReportDataGatherer()

    async def _gather() -> Any:
        async with session_factory() as session:
            return await gatherer.gather(session, account, since_date, until_date)

    report_data = _run_async(_gather())

    # Dashboard comparison mode
    if compare_dashboard:
        from ..reports.compliance_report import ComplianceReportGenerator

        gen = ComplianceReportGenerator()
        typer.echo(gen.generate_comparison(report_data))
        return

    # Generate report in requested format
    from ..reports.compliance_report import ComplianceReportGenerator

    gen = ComplianceReportGenerator()
    today = date.today().isoformat()

    if format.lower() == "pdf":
        output_path = output or Path(f"compliance-report-{account}-{today}.pdf")
        gen.generate_pdf(report_data, output_path)
        typer.echo(
            typer.style(f"PDF report generated: {output_path}", fg=STATUS_COLORS["connected"])
        )

    elif format.lower() == "json":
        output_path = output or Path(f"compliance-report-{account}-{today}.json")
        json_str = gen.generate_json(report_data, output_path)
        typer.echo(json_str)
        typer.echo(
            typer.style(f"\nJSON report saved: {output_path}", fg=STATUS_COLORS["connected"])
        )

    elif format.lower() == "csv":
        output_dir = output or Path(".")
        if output_dir.suffix:
            # User passed a file path, use parent dir
            output_dir = output_dir.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        filenames = gen.generate_csv(report_data, output_dir)
        for fn in filenames:
            typer.echo(f"Exported to {fn}")
        typer.echo(
            typer.style(
                f"\n{len(filenames)} CSV files generated in {output_dir}",
                fg=STATUS_COLORS["connected"],
            )
        )

    else:
        typer.echo(
            typer.style(
                f"Unknown format: {format}. Use pdf, json, or csv.",
                fg=STATUS_COLORS["error"],
            )
        )
        raise typer.Exit(1)
