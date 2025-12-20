"""Main CLI entrypoint for trading engine."""

import typer

from .accounts import accounts_app

app = typer.Typer(
    name="trading-engine",
    help="Multi-account trading engine with FTMO compliance",
    add_completion=False,
)

# Add accounts subcommand group
app.add_typer(accounts_app, name="accounts")


@app.command()
def start() -> None:
    """Start the trading engine."""
    typer.echo("Starting trading engine...")


@app.command()
def stop() -> None:
    """Stop the trading engine."""
    typer.echo("Stopping trading engine...")


@app.command()
def status() -> None:
    """Show trading engine status."""
    typer.echo("Trading engine status: idle")


def cli() -> None:
    """CLI entry point."""
    app()
