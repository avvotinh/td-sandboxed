"""``run_backtest`` — single entrypoint shared by CLI, sweep, walk-forward.

Given a ``BacktestJobConfig`` this builds the ``BacktestRunner``, wires
venue → instrument → data → strategy → (optional) prop-firm compliance actor, runs the
engine, and returns a ``BacktestResult``. All Nautilus imports live here
so callers (CLI, ``parameter_sweep``, ``walk_forward``) stay free of
Nautilus types — they can cross the ``ProcessPoolExecutor`` boundary
carrying only serializable ``BacktestJobConfig`` instances.
"""

from __future__ import annotations

import logging
import types
import typing
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pandas as pd

from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Currency, Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from src.backtesting.bar_converter import dataframe_to_bars
from src.backtesting.commission import commission_per_lot_to_fee_model
from src.backtesting.engine import BacktestRunner, BacktestRunnerConfig
from src.backtesting.prop_firm_preset import load_prop_firm_preset
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

    XAUUSD is special-cased: Nautilus's stock ``default_fx_ccy`` builds
    a ``CurrencyPair`` with ``size_precision=0`` (1-unit lots), which
    rejects the fractional lot sizes a 0.5% risk budget produces on
    gold. We build a gold-specific CurrencyPair with the MT5-broker
    convention of 0.01 lot increment + 3-decimal price precision.
    """
    if symbol == "XAUUSD":
        instrument = _build_xauusd_instrument()
    elif symbol in {"EURUSD", "GBPUSD", "AUDUSD"}:
        instrument = _build_fx_pair_instrument(symbol)
    else:
        instrument = TestInstrumentProvider.default_fx_ccy(symbol)
    # Second tuple entry preserved for backward-compat of the signature
    # only; callers read instrument directly.
    return instrument, str(instrument.id)


def _build_fx_pair_instrument(symbol: str) -> Instrument:
    """FX-pair CurrencyPair with MT5-broker conventions + zero fees.

    Nautilus's stock ``default_fx_ccy`` ships with non-zero
    ``maker_fee``/``taker_fee`` (2 bps) which, on multi-million-unit
    positions a 0.5%-risk sizer produces for FX, eat the account
    via fee burn before strategy edge matters. This builder mirrors
    the XAUUSD custom pattern with FX-pair tweaks:

    * ``size_precision=0`` / ``size_increment=1`` — treat each unit
      as 1 unit of base currency (MT5 micro-lot of 1000 still works
      via ``lot_size=1000`` but the engine accepts smaller).
    * ``price_precision=5`` for non-JPY pairs (Nautilus default).
    * ``maker_fee=taker_fee=0`` — fee model comes from the venue
      ``commission_per_lot_usd`` instead, so the operator can opt in
      to realistic broker fees from a single place.

    Pre-existing instrument-fee handling for XAUUSD already follows
    this no-instrument-fee pattern; this just extends the same
    discipline to the FX whitelist used by the multi-symbol baseline.
    """
    venue = Venue("SIM")
    base_currency = symbol[:3]
    quote_currency = symbol[-3:]
    return CurrencyPair(
        instrument_id=InstrumentId(symbol=Symbol(symbol), venue=venue),
        raw_symbol=Symbol(symbol),
        base_currency=Currency.from_str(base_currency),
        quote_currency=Currency.from_str(quote_currency),
        price_precision=5,
        size_precision=0,
        price_increment=Price(Decimal("0.00001"), 5),
        size_increment=Quantity.from_int(1),
        lot_size=Quantity.from_str("1000"),
        max_quantity=Quantity.from_str("100000000"),
        min_quantity=Quantity.from_str("1"),
        max_price=None,
        min_price=None,
        max_notional=Money(50_000_000.00, USD),
        min_notional=Money(1.00, USD),
        margin_init=Decimal("0.03"),
        margin_maint=Decimal("0.03"),
        maker_fee=Decimal("0"),
        taker_fee=Decimal("0"),
        ts_event=0,
        ts_init=0,
    )


def _build_xauusd_instrument() -> Instrument:
    """XAUUSD as a CurrencyPair with MT5-compatible precisions.

    Conventions chosen:

    * ``size_precision=2`` / ``size_increment=0.01`` — matches the MT5
      micro-lot convention used by every prop-firm backend we care
      about. This is the key bit that lets the bracket strategy submit
      0.5x size partial closes.
    * ``price_precision=3`` — XAUUSD intra-bar prices in the dataset
      (e.g. ``2065.895``) carry at most three decimals; declaring more
      would be padding without information.
    * Notional bounds are loose enough not to bound any realistic
      $100k-account backtest.
    """
    venue = Venue("SIM")
    return CurrencyPair(
        instrument_id=InstrumentId(symbol=Symbol("XAUUSD"), venue=venue),
        raw_symbol=Symbol("XAUUSD"),
        base_currency=Currency.from_str("XAU"),
        quote_currency=Currency.from_str("USD"),
        price_precision=3,
        size_precision=2,
        price_increment=Price(Decimal("0.001"), 3),
        size_increment=Quantity(Decimal("0.01"), 2),
        lot_size=Quantity.from_str("1.00"),
        max_quantity=Quantity.from_str("1000.00"),
        min_quantity=Quantity.from_str("0.01"),
        max_price=None,
        min_price=None,
        max_notional=Money(10_000_000.00, USD),
        min_notional=Money(10.00, USD),
        margin_init=Decimal("0.03"),
        margin_maint=Decimal("0.03"),
        maker_fee=Decimal("0.00002"),
        taker_fee=Decimal("0.00002"),
        ts_event=0,
        ts_init=0,
    )


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
        df = _normalise_parquet_index(df, source=data.path)
        return dataframe_to_bars(df, bar_type=bar_type, instrument=instrument)
    if isinstance(data, TimescaleDataSpec):
        raise NotImplementedError(
            "TimescaleDataSpec requires an async loader wired in by the caller; "
            "use ParquetDataSpec with a pre-warmed cache for walk-forward / sweep."
        )
    raise TypeError(f"Unsupported data spec: {type(data).__name__}")


def _normalise_parquet_index(df: pd.DataFrame, *, source: Any) -> pd.DataFrame:
    """Coerce a parquet OHLCV frame into the tz-aware DatetimeIndex shape Nautilus expects.

    Two on-disk shapes exist in the repo:

    * ``CachedBarLoader.write`` persists a tz-aware ``DatetimeIndex``
      named ``time`` with OHLCV columns only.
    * ``scripts/stitch_chunks_to_window.py`` persists with
      ``index=False`` and a ``time`` int64 (milliseconds since epoch)
      column alongside OHLCV.

    Both are legitimate inputs to :class:`ParquetDataSpec`. We accept
    either and hand a uniform DatetimeIndex shape downstream so
    :func:`dataframe_to_bars` does not need to care.
    """
    if isinstance(df.index, pd.DatetimeIndex):
        if df.index.tz is None:
            raise ValueError(
                f"parquet at {source} has naive DatetimeIndex; expected tz-aware UTC"
            )
        return df

    if "time" not in df.columns:
        raise ValueError(
            f"parquet at {source} has neither a DatetimeIndex nor a 'time' column; "
            "cannot build tz-aware bar timestamps"
        )

    time_series = df["time"]
    if pd.api.types.is_integer_dtype(time_series):
        index = pd.to_datetime(time_series, unit="ms", utc=True)
    else:
        index = pd.to_datetime(time_series, utc=True)
    return df.set_index(pd.DatetimeIndex(index, name="time")).drop(columns=["time"])


def _coerce_strategy_params(
    config_cls: type, params: dict[str, Any]
) -> dict[str, Any]:
    """Coerce primitive YAML values into the types the StrategyConfig expects.

    YAML rounds-trips ``Decimal`` as ``str`` (the canonical way to keep
    full precision), but the dataclass-style ``StrategyConfig`` does
    not auto-convert, so subsequent validation in ``__post_init__``
    breaks on type-mismatched comparisons. We walk the resolved type
    hints on ``config_cls`` and lift ``str`` / ``int`` / ``float``
    inputs into ``Decimal`` for any field annotated as such; everything
    else passes through untouched.
    """
    try:
        hints = typing.get_type_hints(config_cls)
    except Exception:  # pragma: no cover — defensive; e.g. forward refs.
        return params

    coerced: dict[str, Any] = {}
    for name, value in params.items():
        hint = hints.get(name)
        if hint is None:
            coerced[name] = value
            continue
        if _is_decimal_annotation(hint) and not isinstance(value, Decimal):
            if isinstance(value, str):
                coerced[name] = Decimal(value)
            elif isinstance(value, (int, float)):
                coerced[name] = Decimal(str(value))
            else:
                coerced[name] = value
        else:
            coerced[name] = value
    return coerced


def _is_decimal_annotation(hint: Any) -> bool:
    """Return True for ``Decimal`` and ``Decimal | None`` shaped hints."""
    if hint is Decimal:
        return True
    origin = typing.get_origin(hint)
    if origin in (typing.Union, types.UnionType):
        return any(arg is Decimal for arg in typing.get_args(hint))
    return False


def _build_strategy(
    *,
    strategy_name: str,
    instrument: Instrument,
    bar_type: BarType,
    params: dict[str, Any],
) -> BaseStrategy:
    """Instantiate the strategy with merged params."""
    entry = resolve_strategy(strategy_name)
    coerced = _coerce_strategy_params(entry.config_cls, params)
    config = entry.config_cls(
        instrument_id=instrument.id,
        bar_type=bar_type,
        **coerced,
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
        # Epic 9 P0.13: per-firm commission via PerContractFeeModel.
        # ``commission_per_lot_to_fee_model`` returns None when the
        # field is zero; Nautilus accepts ``fee_model=None`` and falls
        # back to the no-fee default, so legacy callers keep their
        # prior behaviour without conditional wrapping.
        fee_model = commission_per_lot_to_fee_model(
            job.venue.commission_per_lot_usd, currency
        )
        oms_type = (
            OmsType.HEDGING
            if job.venue.oms_type == "HEDGING"
            else OmsType.NETTING
        )
        runner.add_venue(
            venue=instrument.id.venue,
            oms_type=oms_type,
            account_type=AccountType.MARGIN,
            starting_balances=[
                Money(float(job.venue.starting_balance), currency)
            ],
            base_currency=currency,
            fee_model=fee_model,
        )
        runner.add_instrument(instrument)
        runner.add_data(bars)

        if job.prop_firm is not None:
            preset = load_prop_firm_preset(job.prop_firm.preset_path)
            rule_engine = _build_prop_firm_rule_engine(
                account_id=job.prop_firm.account_id,
                preset=preset,
                session_timezone=job.prop_firm.session_timezone,
                consistency_block_at=job.prop_firm.consistency_block_at,
                max_drawdown_method=job.prop_firm.max_drawdown_method,
            )
            runner.attach_prop_firm_compliance(
                rule_engine=rule_engine,
                account_id=job.prop_firm.account_id,
                # Epic 12 12.4 — keep actor's daily-session boundary in
                # sync with the rule's reset timezone so breach dedup
                # keys match the trading day the rule sees.
                daily_session_tz=job.prop_firm.session_timezone,
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


def _build_prop_firm_rule_engine(
    *,
    account_id: str,
    preset: Any,
    session_timezone: str = "UTC",
    consistency_block_at: float | None = None,
    max_drawdown_method: str = "equity_peak",
) -> Any:
    """Construct the prop-firm rule set for backtest compliance.

    Delegates to :func:`build_compliance_rule_engine` (Epic 12 12.4)
    via :meth:`ComplianceProfile.from_preset` so backtest wires the
    same rule set as live (Epic 9.5 timezone-aware reset, Epic 9.6
    DD method choice, Epic 9.7 consistency rule).

    ``max_drawdown_method`` defaults to ``"equity_peak"`` to preserve
    pre-12.4 behaviour for legacy callers; FTMO jobs MUST override to
    ``"balance_based"`` (configured per-job via
    :class:`PropFirmSpec.max_drawdown_method`).
    """
    from src.backtesting.dataset.compliance import (
        ComplianceProfile,
        build_compliance_rule_engine,
    )

    profile = ComplianceProfile.from_preset(
        preset,
        session_timezone=session_timezone,
        consistency_block_at=consistency_block_at,
        max_drawdown_method=max_drawdown_method,
    )
    return build_compliance_rule_engine(profile, account_id=account_id)
