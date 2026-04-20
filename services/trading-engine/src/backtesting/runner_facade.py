"""``run_backtest`` — single entrypoint shared by CLI, sweep, walk-forward.

Given a ``BacktestJobConfig`` this builds the ``BacktestRunner``, wires
venue → instrument → data → strategy → (optional) FTMO actor, runs the
engine, and returns a ``BacktestResult``. All Nautilus imports live here
so callers (CLI, ``parameter_sweep``, ``walk_forward``) stay free of
Nautilus types — they can cross the ``ProcessPoolExecutor`` boundary
carrying only serializable ``BacktestJobConfig`` instances.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pandas as pd

from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.objects import Currency, Money
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from src.backtesting.bar_converter import dataframe_to_bars
from src.backtesting.engine import BacktestRunner, BacktestRunnerConfig
from src.backtesting.ftmo_preset import load_ftmo_preset
from src.backtesting.job_config import (
    BacktestJobConfig,
    ParquetDataSpec,
    SyntheticDataSpec,
    TimescaleDataSpec,
)
from src.backtesting.strategy_registry import resolve_strategy
from src.backtesting.synthetic_bars import generate_bars

if TYPE_CHECKING:
    from nautilus_trader.model.data import Bar
    from nautilus_trader.model.instruments import Instrument

    from src.backtesting.result import BacktestResult
    from src.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


_CURRENCY_REGISTRY: dict[str, Currency] = {"USD": USD}


def _resolve_currency(code: str) -> Currency:
    """Map currency code to Nautilus ``Currency``.

    Only the currencies we run backtests against are whitelisted — any
    future expansion requires touching this helper so the surface stays
    auditable.
    """
    try:
        return _CURRENCY_REGISTRY[code.upper()]
    except KeyError as exc:
        known = ", ".join(sorted(_CURRENCY_REGISTRY))
        raise ValueError(
            f"Unsupported currency {code!r}. Known: {known}"
        ) from exc


def _build_instrument(symbol: str) -> tuple[Instrument, BarType]:
    """Return ``(instrument, <unused placeholder>)``.

    Historically this returned a ``BarType`` too; it is constructed
    separately from ``bar_type_suffix`` in ``_bar_type_for``. The tuple
    shape is kept stable so the unit tests can monkeypatch the helper.
    """
    instrument = TestInstrumentProvider.default_fx_ccy(symbol)
    # Second tuple entry preserved for backward-compat of the signature
    # only; callers read instrument directly.
    return instrument, str(instrument.id)


def _bar_type_for(instrument: Instrument, suffix: str) -> BarType:
    return BarType.from_str(f"{instrument.id}-{suffix}")


def _build_bars(
    job: BacktestJobConfig,
    instrument: Instrument,
    bar_type: BarType,
) -> list[Bar]:
    data = job.data
    if isinstance(data, SyntheticDataSpec):
        # Nautilus rejects epoch-0 bars — always stamp a realistic start_ts.
        start_ts = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1_000_000_000)
        return generate_bars(
            pattern=data.pattern,
            count=data.count,
            start_price=data.start_price,
            seed=data.seed,
            start_ts=start_ts,
            bar_type=bar_type,
            price_precision=instrument.price_precision,
            volume_precision=instrument.size_precision,
            drift_scale=data.drift_scale,
            noise_scale=data.noise_scale,
        )
    if isinstance(data, ParquetDataSpec):
        df = pd.read_parquet(data.path)
        return dataframe_to_bars(df, bar_type=bar_type, instrument=instrument)
    if isinstance(data, TimescaleDataSpec):
        raise NotImplementedError(
            "TimescaleDataSpec requires an async loader wired in by the caller; "
            "use ParquetDataSpec with a pre-warmed cache for walk-forward / sweep."
        )
    raise TypeError(f"Unsupported data spec: {type(data).__name__}")


def _build_strategy(
    *,
    strategy_name: str,
    instrument: Instrument,
    bar_type: BarType,
    params: dict[str, Any],
) -> BaseStrategy:
    """Instantiate the strategy with merged params."""
    entry = resolve_strategy(strategy_name)
    config = entry.config_cls(
        instrument_id=instrument.id,
        bar_type=bar_type,
        **params,
    )
    return entry.strategy_cls(config=config)


def run_backtest(
    job: BacktestJobConfig,
    *,
    strategy_overrides: dict[str, Any] | None = None,
) -> BacktestResult:
    """Dispatch a single backtest described by ``job``.

    Args:
        job: Immutable backtest description.
        strategy_overrides: Extra strategy-param overrides merged on top
            of ``job.strategy_params``. Sweep + walk-forward use this to
            vary parameters without mutating the base job.

    Returns:
        ``BacktestResult`` produced by the underlying ``BacktestRunner``.
    """
    merged_params = {**job.strategy_params, **(strategy_overrides or {})}

    instrument, _ = _build_instrument(job.instrument_symbol)
    bar_type = _bar_type_for(instrument, job.bar_type_suffix)
    bars = _build_bars(job, instrument, bar_type)

    currency = _resolve_currency(job.venue.currency)

    runner = BacktestRunner(
        config=BacktestRunnerConfig(
            strategy_name=job.strategy,
            initial_balance=Decimal(job.venue.starting_balance),
            currency=job.venue.currency,
        )
    )
    try:
        runner.add_venue(
            venue=instrument.id.venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            starting_balances=[
                Money(float(job.venue.starting_balance), currency)
            ],
            base_currency=currency,
        )
        runner.add_instrument(instrument)
        runner.add_data(bars)

        if job.ftmo is not None:
            preset = load_ftmo_preset(job.ftmo.preset_path)
            rule_engine = _build_ftmo_rule_engine(
                account_id=job.ftmo.account_id, preset=preset
            )
            runner.attach_ftmo_compliance(
                rule_engine=rule_engine,
                account_id=job.ftmo.account_id,
                bar_type=bar_type,
                venue=instrument.id.venue,
                currency=currency,
            )

        strategy = _build_strategy(
            strategy_name=job.strategy,
            instrument=instrument,
            bar_type=bar_type,
            params=merged_params,
        )
        runner.add_strategy(strategy)

        runner.run(start=job.start, end=job.end)

        final_balance = _read_final_balance(
            runner=runner,
            venue=instrument.id.venue,
            currency=currency,
            fallback=Decimal(job.venue.starting_balance),
        )
        return runner.get_result(final_balance=final_balance)
    finally:
        runner.dispose()


def _read_final_balance(
    *,
    runner: BacktestRunner,
    venue: Any,
    currency: Currency,
    fallback: Decimal,
) -> Decimal:
    """Read the post-run account balance from the portfolio.

    Falls back to ``fallback`` (starting balance) only on expected
    lookup failures (mocked engine in unit tests, rare mid-construction
    cache reads). Other exceptions propagate so a misbehaving engine
    doesn't silently return a neutral-PnL result that the sweep would
    rank as a normal combo.
    """
    try:
        account = runner.engine.portfolio.account(venue)
    except (AttributeError, LookupError):
        logger.warning(
            "portfolio account unavailable (engine likely mocked); "
            "using starting balance for final_balance"
        )
        return fallback
    if account is None:
        return fallback
    try:
        balance = account.balance_total(currency)
    except (AttributeError, LookupError):
        logger.warning(
            "balance_total read failed for %s; using starting balance", currency
        )
        return fallback
    # Nautilus ``Money`` exposes ``as_decimal()``. Some test doubles return
    # plain numerics — accept both.
    as_decimal = getattr(balance, "as_decimal", None)
    if callable(as_decimal):
        return Decimal(as_decimal())
    try:
        return Decimal(str(balance))
    except (ValueError, TypeError, ArithmeticError):
        logger.warning(
            "balance value %r not convertible to Decimal; using starting balance",
            balance,
        )
        return fallback


def _build_ftmo_rule_engine(*, account_id: str, preset: Any) -> Any:
    """Construct the minimum FTMO rule set for backtest compliance.

    Kept small + importable inside the function so unit tests that do
    not touch the FTMO path never pay the import cost.
    """
    from src.rules.engine import RuleEngine
    from src.rules.types.drawdown import DailyLossLimitRule, MaxDrawdownRule

    return RuleEngine(
        account_id=account_id,
        rules=[
            DailyLossLimitRule(threshold_percent=preset.daily_loss_pct),
            MaxDrawdownRule(threshold_percent=preset.max_drawdown_pct),
        ],
        strict_mode=True,
    )
