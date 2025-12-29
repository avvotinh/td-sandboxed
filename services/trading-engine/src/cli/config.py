"""CLI commands for configuration management."""

from __future__ import annotations

import json
import os

import typer
import yaml
from typing_extensions import Annotated

from ..config.loader import ConfigLoader, ConfigValidationError, ConfigSyntaxError
from .constants import STATUS_COLORS

config_app = typer.Typer(help="Configuration management")

# Fields to mask - any field name containing these substrings (case-insensitive)
# Include both underscore and no-underscore variants to catch camelCase
SECRETS_TO_MASK = ["password", "token", "secret", "api_key", "apikey", "credential", "auth"]


def mask_secrets(config_dict: dict) -> dict:
    """Recursively mask secret fields in config dictionary.

    Args:
        config_dict: Configuration dictionary.

    Returns:
        Dictionary with secret fields masked.
    """
    result = {}
    for key, value in config_dict.items():
        key_lower = key.lower()
        if any(secret in key_lower for secret in SECRETS_TO_MASK):
            result[key] = "***"
        elif isinstance(value, dict):
            result[key] = mask_secrets(value)
        elif isinstance(value, list):
            result[key] = [mask_secrets(v) if isinstance(v, dict) else v for v in value]
        else:
            result[key] = value
    return result


@config_app.command("dump")
def dump_config(
    output_format: Annotated[
        str, typer.Option("--format", "-f", help="Output format (yaml/json)")
    ] = "yaml",
) -> None:
    """Show resolved configuration with secrets masked."""
    # Validate format parameter
    if output_format not in ("yaml", "json"):
        typer.echo(
            typer.style(
                f"Invalid format: {output_format}. Use 'yaml' or 'json'",
                fg=STATUS_COLORS["error"],
            )
        )
        raise typer.Exit(1)

    config_path = os.getenv("ACCOUNTS_CONFIG", "configs/accounts.yaml")
    try:
        loader = ConfigLoader(config_path)
        config = loader.load()
        config_dict = config.model_dump()
        masked = mask_secrets(config_dict)

        if output_format == "json":
            typer.echo(json.dumps(masked, indent=2))
        else:
            typer.echo(yaml.dump(masked, default_flow_style=False, sort_keys=False))
    except FileNotFoundError:
        typer.echo(
            typer.style(f"Config not found: {config_path}", fg=STATUS_COLORS["error"])
        )
        raise typer.Exit(1)
    except ConfigSyntaxError as e:
        typer.echo(typer.style(str(e), fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)
    except ConfigValidationError as e:
        typer.echo(typer.style(str(e), fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)


@config_app.command("validate")
def validate_config() -> None:
    """Validate configuration without starting engine."""
    config_path = os.getenv("ACCOUNTS_CONFIG", "configs/accounts.yaml")
    try:
        loader = ConfigLoader(config_path)
        config = loader.load()
        typer.echo(
            typer.style("Configuration valid", fg=STATUS_COLORS["connected"])
        )
        typer.echo(f"  Accounts: {len(config.accounts)}")
        for acc in config.accounts:
            typer.echo(f"    - {acc.id}: {acc.name}")
    except FileNotFoundError:
        typer.echo(
            typer.style(f"Config not found: {config_path}", fg=STATUS_COLORS["error"])
        )
        raise typer.Exit(1)
    except ConfigSyntaxError as e:
        typer.echo(typer.style(str(e), fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)
    except ConfigValidationError as e:
        typer.echo(typer.style(str(e), fg=STATUS_COLORS["error"]))
        raise typer.Exit(1)
