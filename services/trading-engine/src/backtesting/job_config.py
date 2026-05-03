"""``BacktestJobConfig`` — single declarative object describing a backtest.

The CLI, parameter sweep, and walk-forward all consume one of these to
dispatch a backtest via ``run_backtest``. Declaring a job up-front keeps
the Nautilus composition boilerplate out of the CLI + sweep + walk-
forward layers.

A job is fully serializable (Pydantic) so it can cross the process
boundary into ``ProcessPoolExecutor`` workers without pickling live
Nautilus objects.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from src.backtesting.strategy_registry import resolve_strategy


# Symbols we know how to construct via ``TestInstrumentProvider``. Adding
# a new symbol requires either a real-broker instrument loader (deferred)
# or extending this whitelist plus a smoke test.
_SUPPORTED_SYMBOLS: frozenset[str] = frozenset(
    {
        "EUR/USD",
        "GBP/USD",
        "USD/JPY",
        "USD/CAD",
        "AUD/USD",
        "XAUUSD",
    }
)


class UnsupportedInstrumentError(ValueError):
    """Raised when a job references an instrument symbol we cannot build."""


def supported_symbols() -> tuple[str, ...]:
    """Return the whitelist in a stable, displayable order."""
    return tuple(sorted(_SUPPORTED_SYMBOLS))


class _Frozen(BaseModel):
    """Shared immutability + pickle-safety config."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --- Data specs -------------------------------------------------------


class SyntheticDataSpec(_Frozen):
    """Generate deterministic synthetic bars (no I/O)."""

    kind: Literal["synthetic"] = "synthetic"
    pattern: Literal["trending", "mean_reverting", "flat"]
    count: int = Field(..., gt=0)
    start_price: float = Field(..., gt=0)
    seed: int = 42
    drift_scale: float = 1.0
    noise_scale: float = 1.0


class TimescaleDataSpec(_Frozen):
    """Load bars from TimescaleDB via ``CachedBarLoader``."""

    kind: Literal["timescale"] = "timescale"
    start: datetime
    end: datetime
    cache_dir: Path | None = None

    @model_validator(mode="after")
    def _check_range(self) -> TimescaleDataSpec:
        if self.end <= self.start:
            raise ValueError("end must be strictly after start")
        return self


class ParquetDataSpec(_Frozen):
    """Read bars from a pre-built Parquet shard (no TimescaleDB roundtrip)."""

    kind: Literal["parquet"] = "parquet"
    path: Path

    @field_validator("path")
    @classmethod
    def _no_traversal(cls, v: Path) -> Path:
        if ".." in v.parts:
            raise ValueError(
                f"Path traversal via '..' not allowed in ParquetDataSpec.path: {v}"
            )
        return v


DataSpec = Annotated[
    SyntheticDataSpec | TimescaleDataSpec | ParquetDataSpec,
    Field(discriminator="kind"),
]


# --- Supporting specs -------------------------------------------------


class VenueSpec(_Frozen):
    """Backtest venue + starting balance.

    ``commission_per_lot_usd`` (Epic 9 P0.13) wires a flat per-lot fee
    into the simulated venue so backtest PnL matches live PnL after
    commission. Defaults to ``0`` (no commission) for backward
    compatibility; firm-bound jobs typically derive this from the
    firm's :class:`CommissionProfile` via
    ``src.backtesting.commission.resolve_commission_profile``.
    """

    name: str = "SIM"
    starting_balance: Decimal = Field(..., gt=0)
    currency: str = "USD"
    commission_per_lot_usd: Decimal = Field(default=Decimal("0"), ge=0)


class PropFirmSpec(_Frozen):
    """Optional prop-firm compliance wiring.

    ``session_timezone`` and ``consistency_block_at`` are Epic 12 12.4
    additions. ``session_timezone`` flows into both the
    :class:`DailyLossLimitRule` reset (Epic 9.5) and the
    :class:`PropFirmComplianceActor`'s daily-session boundary so dedup
    keys match the configured trading day. ``consistency_block_at``
    enables Epic 9.7 :class:`ConsistencyRule` when set; ``None`` keeps
    backward compatibility with pre-12.4 jobs (rule omitted).
    """

    preset_path: Path
    account_id: str
    session_timezone: str = "UTC"
    consistency_block_at: float | None = None
    # FTMO Challenge requires ``"balance_based"`` (Epic 9.6 — DD from
    # static initial balance, not running peak). Default
    # ``"equity_peak"`` is the conservative no-op for non-FTMO callers.
    max_drawdown_method: str = "equity_peak"

    @field_validator("preset_path")
    @classmethod
    def _no_traversal(cls, v: Path) -> Path:
        if ".." in v.parts:
            raise ValueError(
                f"Path traversal via '..' not allowed in PropFirmSpec.preset_path: {v}"
            )
        return v

    @field_validator("consistency_block_at")
    @classmethod
    def _check_consistency_block(cls, v: float | None) -> float | None:
        if v is not None and not 0 < v <= 100:
            raise ValueError(
                f"consistency_block_at must be in (0, 100], got {v}"
            )
        return v

    @field_validator("max_drawdown_method")
    @classmethod
    def _check_dd_method(cls, v: str) -> str:
        valid = {"equity_peak", "balance_based"}
        if v not in valid:
            raise ValueError(
                f"max_drawdown_method must be one of {sorted(valid)}, got {v!r}"
            )
        return v


# --- Main job config --------------------------------------------------


class BacktestJobConfig(_Frozen):
    """Declarative description of one backtest run.

    Use :meth:`with_strategy_params` / :meth:`with_window` to derive
    variants (parameter sweep, walk-forward folds) without mutating the
    original — every modification returns a new instance.
    """

    strategy: str
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    venue: VenueSpec
    instrument_symbol: str
    bar_type_suffix: str = "1-MINUTE-BID-EXTERNAL"
    data: DataSpec
    prop_firm: PropFirmSpec | None = None
    start: datetime | None = None
    end: datetime | None = None

    @field_validator("strategy")
    @classmethod
    def _validate_strategy(cls, v: str) -> str:
        resolve_strategy(v)  # raises UnknownStrategyError if invalid
        return v

    @field_validator("instrument_symbol")
    @classmethod
    def _validate_symbol(cls, v: str) -> str:
        if v not in _SUPPORTED_SYMBOLS:
            known = ", ".join(sorted(_SUPPORTED_SYMBOLS))
            raise UnsupportedInstrumentError(
                f"Unsupported instrument symbol {v!r}. Supported: {known}"
            )
        return v

    def with_strategy_params(self, **overrides: Any) -> BacktestJobConfig:
        """Return a new job whose ``strategy_params`` are merged with overrides."""
        merged = {**self.strategy_params, **overrides}
        return self.model_copy(update={"strategy_params": merged})

    def with_window(
        self, *, start: datetime | None, end: datetime | None
    ) -> BacktestJobConfig:
        """Return a new job with a narrowed run window (walk-forward folds)."""
        return self.model_copy(update={"start": start, "end": end})

    @classmethod
    def from_yaml(cls, path: Path) -> BacktestJobConfig:
        """Load a job from a YAML file."""
        data = yaml.safe_load(Path(path).read_text())
        if not isinstance(data, dict):
            raise ValueError(f"Job YAML must contain a mapping, got {type(data)!r}")
        return cls.model_validate(data)
