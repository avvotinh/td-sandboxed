"""Result Contract v2 writer — the keystone JSON schema of v2.

Serializes a finished :class:`BacktestResult` + its
:class:`BacktestJobConfig` into the versioned schema defined in
``docs/v2/01-architecture.md`` §4. The chart viewer (P2) and
backtest-analyst tooling consume these files from ``results/``
(gitignored); study verdicts reference runs by ``run_id``.

Schema changes MUST bump ``SCHEMA_VERSION`` and be logged in
``docs/v2/decisions.md``.
"""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.lab.job_config import (
    BacktestJobConfig,
    ParquetDataSpec,
    SyntheticDataSpec,
)
from src.lab.result import BacktestResult, IndicatorSeries, TradeRecord
from src.kernel.instruments.contract_specs import get_contract_spec

SCHEMA_VERSION = "2"

_AGGREGATION_PREFIXES = {
    "SECOND": "S",
    "MINUTE": "M",
    "HOUR": "H",
    "DAY": "D",
    "WEEK": "W",
    "MONTH": "MN",
}


def make_run_id(strategy: str, symbol: str, timeframe: str) -> str:
    """``{strategy}-{symbol}-{tf}-{YYYYMMDD-HHMMSS}`` (UTC now, lowercased ids).

    ``symbol`` is sanitized for filesystem use: run_ids become file
    names (``results/<run_id>.json``), so slash variants like
    ``EUR/USD`` collapse to ``eurusd``.
    """
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    safe_symbol = symbol.lower().replace("/", "")
    return f"{strategy}-{safe_symbol}-{timeframe.lower()}-{stamp}"


def timeframe_from_suffix(suffix: str) -> str:
    """Bar-type suffix → compact timeframe: ``5-MINUTE-LAST-EXTERNAL`` → ``M5``.

    Unknown shapes fall back to the raw suffix so the payload never
    loses information.
    """
    parts = suffix.split("-")
    if len(parts) >= 2 and parts[0].isdigit():
        prefix = _AGGREGATION_PREFIXES.get(parts[1].upper())
        if prefix is not None:
            return f"{prefix}{parts[0]}"
    return suffix


def build_result_payload(
    result: BacktestResult,
    *,
    job: BacktestJobConfig,
    run_id: str,
) -> dict[str, Any]:
    """Assemble the full Contract v2 dict for one backtest run."""
    return {
        "schema_version": SCHEMA_VERSION,
        "run": _run_section(job, result, run_id),
        "account": {
            "initial_balance": float(result.initial_balance),
            "final_balance": float(result.final_balance),
            "currency": job.venue.currency,
            "risk_profile": "demo",
        },
        "trades": [_trade_payload(trade) for trade in result.trades],
        "equity_curve": [
            {"ts": ts.isoformat(), "equity": float(equity)}
            for ts, equity in result.equity_curve
        ],
        "indicators": [
            _indicator_payload(series) for series in result.indicators
        ],
        "metrics": (
            result.metrics.model_dump(mode="json")
            if result.metrics is not None
            else None
        ),
        "breaches": [
            {
                "ts": breach.ts.isoformat(),
                "rule_name": breach.rule_name,
                "current_value": breach.current_value,
                "threshold_value": breach.threshold_value,
                "message": breach.message,
            }
            for breach in result.breaches
        ],
    }


def write_result_json(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` as pretty JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )


# --- Section builders ---------------------------------------------------


def _run_section(
    job: BacktestJobConfig, result: BacktestResult, run_id: str
) -> dict[str, Any]:
    """The ``run`` block: identity, window, params, provenance."""
    return {
        "run_id": run_id,
        "strategy": job.strategy,
        "symbol": job.instrument_symbol,
        "timeframe": timeframe_from_suffix(job.bar_type_suffix),
        "window": _window(job, result),
        "params": _normalize_params(job.strategy_params),
        "data_ref": _data_ref(job, result),
        "engine": {
            "nautilus_version": _nautilus_version(),
            "commit": _git_commit(),
        },
    }


def _normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Snapshot strategy params with Decimals lifted to JSON numbers.

    YAML round-trips ``Decimal`` params as strings; the Contract v2
    ``run.params`` block should carry numbers so downstream consumers
    (viewer filters, sweep tooling) can compare without parsing.
    """
    return {
        key: float(value) if isinstance(value, Decimal) else value
        for key, value in params.items()
    }


def _window(job: BacktestJobConfig, result: BacktestResult) -> dict[str, Any]:
    """Run window: name derived from the data spec, start/end ISO."""
    data = job.data
    if isinstance(data, ParquetDataSpec):
        name = Path(data.path).stem
    elif isinstance(data, SyntheticDataSpec):
        name = "synthetic"
    else:
        name = "full"
    start = job.start or result.start
    end = job.end or result.end
    return {
        "name": name,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
    }


def _data_ref(job: BacktestJobConfig, result: BacktestResult) -> dict[str, Any]:
    """Dataset provenance: manifest/parquet ref + fingerprint (best-effort)."""
    data = job.data
    if isinstance(data, ParquetDataSpec):
        ref: str | None = Path(data.path).as_posix()
        entry: str | None = None
    elif isinstance(data, SyntheticDataSpec):
        ref = f"synthetic:{data.pattern}:count={data.count}:seed={data.seed}"
        entry = None
    else:
        ref = None
        entry = None

    fingerprint: Any = None
    snapshot = result.config_snapshot or {}
    for key in ("fingerprint", "dataset_fingerprint", "data_fingerprint"):
        if snapshot.get(key):
            fingerprint = snapshot[key]
            break
    return {"manifest": ref, "entry": entry, "fingerprint": fingerprint}


def _nautilus_version() -> str | None:
    try:
        return importlib.metadata.version("nautilus_trader")
    except importlib.metadata.PackageNotFoundError:
        return None


def _git_commit() -> str | None:
    """``git rev-parse --short HEAD`` best-effort; None on any failure."""
    try:
        proc = subprocess.run(  # noqa: S603, S607 — fixed argv, no user input
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            cwd=Path(__file__).resolve().parent,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    commit = proc.stdout.strip()
    return commit or None


def _trade_payload(trade: TradeRecord) -> dict[str, Any]:
    """One Contract v2 trade row from a :class:`TradeRecord`."""
    row: dict[str, Any] = {
        "trade_id": trade.trade_id,
        "side": "LONG" if trade.side == "BUY" else "SHORT",
        "entry": {
            "ts": trade.entry_ts.isoformat(),
            "price": float(trade.entry_price),
            "kind": "market",
            "reason": None,
        },
        "exit": {
            "ts": trade.exit_ts.isoformat(),
            "price": float(trade.exit_price),
            "reason": None,
        },
        "pnl": round(float(trade.pnl), 2),
        "r_multiple": _r_multiple(trade),
        "sl": float(trade.sl_price) if trade.sl_price is not None else None,
        "tp": float(trade.tp_price) if trade.tp_price is not None else None,
        "sl_path": _sl_path(trade),
    }
    try:
        spec = get_contract_spec(trade.symbol)
    except ValueError:
        # No contract spec — emit raw engine units instead of guessing
        # lot economics (fail-soft variant of the fail-loud sizer rule).
        row["quantity_units"] = float(trade.quantity)
    else:
        row["quantity_lots"] = float(spec.units_to_lots(trade.quantity))
    return row


def _r_multiple(trade: TradeRecord) -> float | None:
    """Price-based R multiple; None when SL missing or risk non-positive.

    LONG:  (exit - entry) / (entry - sl)
    SHORT: (entry - exit) / (sl - entry)
    """
    if trade.sl_price is None:
        return None
    if trade.side == "BUY":
        denominator = trade.entry_price - trade.sl_price
        numerator = trade.exit_price - trade.entry_price
    else:
        denominator = trade.sl_price - trade.entry_price
        numerator = trade.entry_price - trade.exit_price
    if denominator <= 0:
        return None
    return round(float(numerator / denominator), 3)


def _sl_path(trade: TradeRecord) -> list[dict[str, Any]]:
    """SL modification history; same-ts writes collapse to the last one."""
    deduped: dict[datetime, float] = {}
    for update in trade.sl_updates:
        deduped[update.ts] = float(update.price)
    return [
        {"ts": ts.isoformat(), "price": price, "reason": None}
        for ts, price in sorted(deduped.items())
    ]


def _indicator_payload(series: IndicatorSeries) -> dict[str, Any]:
    """IndicatorSeries → Contract v2 shape (epoch-second point times)."""
    return {
        "key": series.key,
        "title": series.title,
        "pane": series.pane,
        "color": series.color,
        "points": [
            {"time": int(ts.timestamp()), "value": value}
            for ts, value in series.points
        ],
        "levels": list(series.levels),
    }
