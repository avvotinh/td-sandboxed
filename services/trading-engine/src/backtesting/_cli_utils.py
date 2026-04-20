"""Shared helpers for the backtest CLI subcommand."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from src.backtesting.result import BacktestResult


_DURATION_RE = re.compile(r"^(\d+)([smhd])$")


def parse_duration(text: str) -> timedelta:
    """Parse ``'30d' | '6h' | '45m' | '30s'`` into a ``timedelta``."""
    match = _DURATION_RE.match(text.strip().lower())
    if not match:
        raise ValueError(
            f"Invalid duration {text!r}; expected like '30d', '6h', '45m', '30s'"
        )
    n, unit = int(match.group(1)), match.group(2)
    if unit == "d":
        return timedelta(days=n)
    if unit == "h":
        return timedelta(hours=n)
    if unit == "m":
        return timedelta(minutes=n)
    return timedelta(seconds=n)


def parse_date(text: str) -> datetime:
    """Parse an ISO-format date into a UTC-aware ``datetime``."""
    from datetime import UTC

    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def read_yaml(path: Path) -> Any:
    """Read a YAML file, raising ``FileNotFoundError`` or ``ValueError`` clearly."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    loaded = yaml.safe_load(path.read_text())
    return loaded


def result_to_json_dict(result: BacktestResult) -> dict[str, Any]:
    """Machine-readable serialization of a ``BacktestResult`` for ``--json`` output."""
    return {
        "strategy_name": result.strategy_name,
        "start": result.start.isoformat() if result.start else None,
        "end": result.end.isoformat() if result.end else None,
        "initial_balance": str(result.initial_balance),
        "final_balance": str(result.final_balance),
        "net_pnl": str(Decimal(result.final_balance) - Decimal(result.initial_balance)),
        "trades": len(result.trades),
        "breaches": len(result.breaches),
        "metrics": (
            result.metrics.model_dump(mode="json") if result.metrics is not None else None
        ),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
