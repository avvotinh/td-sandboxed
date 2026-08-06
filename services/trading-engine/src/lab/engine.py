"""BacktestRunner — thin façade over ``nautilus_trader.backtest.BacktestEngine``.

The runner's job is to compose a backtest in a way that keeps the rest of
our stack (rule engine, strategies, prop-firm metrics) independent of
Nautilus internals. Composition order matters — ``add_venue`` must precede
``add_instrument``, and the prop-firm compliance actor must be attached
before ``run()``.

For unit-level tests the underlying engine is mocked. End-to-end
correctness is covered by ``tests/integration/test_backtest_smoke.py``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import OrderSide, OrderType
from nautilus_trader.model.events import OrderInitialized, OrderUpdated
from nautilus_trader.model.objects import Currency, Money
from pydantic import BaseModel, ConfigDict, Field

from src.lab.prop_firm_actor import PropFirmComplianceActor
from src.lab.prop_firm_preset import PropFirmPreset
from src.lab.metrics.calculator import calculate_metrics
from src.lab.recorder.equity_recorder import (
    EquityRecorderActor,
    EquityRecorderActorConfig,
)
from src.lab.result import (
    BacktestResult,
    IndicatorSeries,
    SlUpdate,
    TradeRecord,
)

if TYPE_CHECKING:
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.identifiers import Venue

    from src.config.firm_profile import RegimeConfig
    from src.kernel.regime.actor import RegimeActor, RegimeAuditHook
    from src.kernel.regime.state_store import RegimeStateStore
    from src.rules.engine import RuleEngine

logger = logging.getLogger(__name__)


def _pos_pnl_decimal(pnl: Any) -> Decimal:
    """Coerce a Nautilus ``Money`` (or compatible) into ``Decimal``.

    ``str(Money(123.45, USD))`` is ``"123.45 USD"`` which ``Decimal``
    can't parse. ``Money`` exposes ``.as_decimal()``; we type-check
    explicitly so a future Nautilus version that drops ``as_decimal``
    or a third-party object that happens to expose the same name
    cannot silently return garbage. We fall through to
    ``Decimal(str(...))`` for ints / floats / Decimals already in
    decimal-stringifiable shape, and treat ``None`` as zero PnL (the
    position closed with no realised cash flow).
    """
    if pnl is None:
        return Decimal("0")
    if isinstance(pnl, Money):
        return pnl.as_decimal()
    return Decimal(str(pnl))


def _ns_to_utc(ns: int) -> datetime:
    """Nautilus ns timestamp → tz-aware UTC datetime (second resolution)."""
    return datetime.fromtimestamp(ns // 1_000_000_000, tz=UTC)


def _to_decimal(value: Any) -> Decimal | None:
    """Best-effort ``Decimal`` coercion for Nautilus price-like objects."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError:
        return None


def _initial_sl_price(order: Any) -> Decimal | None:
    """The SL leg's *initial* trigger price.

    ``order.trigger_price`` reflects the latest modification, so a
    trailed SL would read as its final value. The original trigger is
    recorded on the ``OrderInitialized`` event's ``options`` mapping;
    we fall back to the live attribute when the event (or the key) is
    missing — correct for never-modified legs, best-effort otherwise.
    """
    for event in getattr(order, "events", ()) or ():
        if isinstance(event, OrderInitialized):
            options = getattr(event, "options", None) or {}
            initial = _to_decimal(options.get("trigger_price"))
            if initial is not None:
                return initial
            break
    return _to_decimal(getattr(order, "trigger_price", None))


def _sl_update_history(order: Any) -> tuple[SlUpdate, ...]:
    """Chronological SL modifications (BE move + trailing ratchets)."""
    updates: list[SlUpdate] = []
    for event in getattr(order, "events", ()) or ():
        if not isinstance(event, OrderUpdated):
            continue
        price = _to_decimal(event.trigger_price)
        if price is None:
            continue
        updates.append(SlUpdate(ts=_ns_to_utc(event.ts_event), price=price))
    updates.sort(key=lambda u: u.ts)
    return tuple(updates)


def _extract_bracket_levels(
    cache: Any, position_id: Any
) -> tuple[Decimal | None, Decimal | None, tuple[SlUpdate, ...]]:
    """Recover (initial SL, TP, SL-update history) for one position.

    Our strategies enter with market brackets whose children are a
    STOP_MARKET SL leg and a LIMIT TP leg (``BaseStrategy._build_bracket_args``),
    so order type identifies the leg. Multiple same-type legs (should
    not happen with one bracket per position) resolve to the earliest
    by ``ts_init``. Any cache/lookup failure degrades to ``(None, None, ())``
    — the chart viewer treats levels as optional enrichment.
    """
    try:
        orders = list(cache.orders_for_position(position_id))
    except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
        logger.debug(
            "orders_for_position(%s) failed; trade emitted without "
            "bracket levels: %s",
            position_id,
            exc,
        )
        return None, None, ()

    orders.sort(key=lambda o: getattr(o, "ts_init", 0))
    sl_price: Decimal | None = None
    tp_price: Decimal | None = None
    sl_updates: tuple[SlUpdate, ...] = ()
    for order in orders:
        order_type = getattr(order, "order_type", None)
        if order_type == OrderType.STOP_MARKET and sl_price is None:
            sl_price = _initial_sl_price(order)
            sl_updates = _sl_update_history(order)
        elif order_type == OrderType.LIMIT and tp_price is None:
            tp_price = _to_decimal(getattr(order, "price", None))
    return sl_price, tp_price, sl_updates


class BacktestRunnerConfig(BaseModel):
    """Configuration for a single backtest run.

    Prefer :meth:`from_preset` over passing prop-firm threshold fields
    directly so the backtest shares the same compliance numbers the
    live rule engine enforces (see
    ``.claude/rules/common/sandboxed-domain.md``).
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    strategy_name: str
    initial_balance: Decimal = Field(..., gt=0)
    currency: str = "USD"
    profit_target_pct: float = 10.0
    max_dd_pct: float = 10.0
    min_trading_days: int = 4

    @classmethod
    def from_preset(
        cls,
        *,
        strategy_name: str,
        initial_balance: Decimal,
        preset: PropFirmPreset,
        currency: str = "USD",
    ) -> BacktestRunnerConfig:
        """Build a config whose prop-firm thresholds come from ``preset``."""
        return cls(
            strategy_name=strategy_name,
            initial_balance=initial_balance,
            currency=currency,
            profit_target_pct=preset.profit_target_pct,
            max_dd_pct=preset.max_drawdown_pct,
            min_trading_days=preset.min_trading_days,
        )


class BacktestRunner:
    """Façade orchestrating a Nautilus backtest with prop-firm compliance."""

    def __init__(self, config: BacktestRunnerConfig) -> None:
        self.config = config
        self._engine: BacktestEngine = BacktestEngine(config=BacktestEngineConfig())
        self._prop_firm_actor: PropFirmComplianceActor | None = None
        self._equity_recorder: EquityRecorderActor | None = None
        self._regime_actor: RegimeActor | None = None
        self._start: datetime | None = None
        self._end: datetime | None = None

    @property
    def engine(self) -> BacktestEngine:
        return self._engine

    @property
    def prop_firm_actor(self) -> PropFirmComplianceActor | None:
        return self._prop_firm_actor

    @property
    def equity_recorder(self) -> EquityRecorderActor | None:
        return self._equity_recorder

    @property
    def regime_actor(self) -> RegimeActor | None:
        return self._regime_actor

    # ---- Composition ------------------------------------------------------

    def add_venue(self, **kwargs: Any) -> None:
        """Add a simulated venue. Must be called before ``add_instrument``."""
        self._engine.add_venue(**kwargs)

    def add_instrument(self, instrument: Any) -> None:
        self._engine.add_instrument(instrument)

    def add_data(self, data: Any) -> None:
        self._engine.add_data(data)

    def add_strategy(self, strategy: Any) -> None:
        self._engine.add_strategy(strategy)

    def attach_prop_firm_compliance(
        self,
        *,
        rule_engine: RuleEngine,
        account_id: str,
        daily_session_tz: str = "UTC",
        bar_type: Any = None,
        venue: Venue | None = None,
        currency: Currency = USD,
    ) -> PropFirmComplianceActor:
        """Build + register an ``PropFirmComplianceActor`` against this engine.

        ``bar_type`` is the ``BarType`` the actor should subscribe to on
        start — pass the same ``BarType`` you used for ``add_data``. When
        omitted the actor still registers but won't receive on_bar events;
        useful when tests exercise the actor via its public methods only.

        ``venue`` + ``currency`` let the actor read real equity from the
        portfolio. When omitted (unit-test path) equity reads return
        ``None`` and ``on_bar`` is a no-op.

        Delegates to :func:`src.engine.actors.build_compliance_actor` so
        backtest and live (story 10.5d) construct the actor identically.
        """
        # Lazy import to break the cycle:
        #   backtesting.engine → engine.actors → backtesting.prop_firm_actor
        # would otherwise re-enter backtesting.engine at module load time.
        from src.engine.actors import build_compliance_actor

        actor = build_compliance_actor(
            account_id=account_id,
            initial_balance=self.config.initial_balance,
            rule_engine=rule_engine,
            daily_session_tz=daily_session_tz,
            bar_type=bar_type,
            venue=venue,
            currency=currency,
        )
        self._engine.add_actor(actor)
        self._prop_firm_actor = actor
        return actor

    def attach_equity_recorder(
        self,
        *,
        bar_type: Any = None,
        venue: Venue | None = None,
        currency: Currency = USD,
        initial_balance: Decimal | None = None,
    ) -> EquityRecorderActor:
        """Build + register an ``EquityRecorderActor`` against this engine.

        Contract v2 P1 (gap G2): the equity curve no longer depends on
        the prop-firm compliance actor — attach this recorder on every
        run so jobs without a ``prop_firm`` block still get a populated
        curve (and thus drawdown/Sharpe metrics).

        Mirrors :meth:`attach_prop_firm_compliance` parameter semantics:
        ``bar_type`` should match ``add_data``; ``venue`` + ``currency``
        let the actor read real portfolio equity (omit both for the
        unit-test path where ``on_bar`` is a no-op). ``initial_balance``
        defaults to the runner config's starting balance.
        """
        actor = EquityRecorderActor(
            config=EquityRecorderActorConfig(
                initial_balance=(
                    initial_balance
                    if initial_balance is not None
                    else self.config.initial_balance
                ),
                bar_type=bar_type,
                venue=venue,
                currency=currency,
            )
        )
        self._engine.add_actor(actor)
        self._equity_recorder = actor
        return actor

    def attach_regime(
        self,
        *,
        regime_config: RegimeConfig,
        bar_type: BarType,
        regime_state: RegimeStateStore,
        audit_hook: RegimeAuditHook | None = None,
    ) -> RegimeActor | None:
        """Build + register a ``RegimeActor`` against this engine (story 15.8).

        Mirrors :meth:`attach_prop_firm_compliance`: delegates to
        :func:`src.engine.actors.build_regime_actor` so backtest and live
        (stories 15.10/15.11) construct the regime pipeline identically. Returns
        ``None`` when ``regime_config.enabled`` is ``False`` — no actor is added,
        so a disabled regime block costs nothing (default-OFF parity).

        The caller owns the shared ``regime_state`` and injects the **same**
        object into the strategy (``run_backtest``), so the actor's per-bar
        ``publish`` is exactly what the strategy's entry gate reads.

        ``audit_hook`` stays ``None`` for backtest, so ``build_regime_actor``
        derives ``audit_to_db=False`` and the run writes **zero** rows to the
        live ``audit_logs`` hypertable (review R-E). Live (15.11) passes a hook
        over the existing ``AuditWriter`` queue.

        ``bar_type`` should be the same ``BarType`` passed to ``add_data`` — its
        symbol leg selects the per-instrument regime calibration.
        """
        # Lazy import to break the cycle:
        #   backtesting.engine → engine.actors → backtesting.prop_firm_actor
        # would otherwise re-enter backtesting.engine at module load time
        # (same reason attach_prop_firm_compliance imports locally).
        from src.engine.actors import build_regime_actor

        actor = build_regime_actor(
            regime_config=regime_config,
            bar_type=bar_type,
            regime_state=regime_state,
            audit_hook=audit_hook,
        )
        if actor is not None:
            self._engine.add_actor(actor)
            self._regime_actor = actor
        return actor

    # ---- Execution --------------------------------------------------------

    def run(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> None:
        """Run the backtest. ``start``/``end`` forwarded to Nautilus."""
        self._start = start
        self._end = end
        kwargs: dict[str, Any] = {}
        if start is not None:
            kwargs["start"] = start
        if end is not None:
            kwargs["end"] = end
        self._engine.run(**kwargs)

    def get_result(
        self,
        *,
        final_balance: Decimal,
        indicators: tuple[IndicatorSeries, ...] = (),
    ) -> BacktestResult:
        """Assemble a ``BacktestResult`` from engine + actor state.

        The equity curve prefers the dedicated ``EquityRecorderActor``
        (Contract v2 P1) when it recorded anything; otherwise it falls
        back to the prop-firm actor's curve so old callers/tests that
        only attach compliance keep working.
        """
        equity_curve = self._select_equity_curve()
        breaches = (
            self._prop_firm_actor.breaches if self._prop_firm_actor is not None else []
        )
        trades = self._extract_trades()

        start = self._start or (
            equity_curve[0][0] if equity_curve else datetime.now()
        )
        end = self._end or (
            equity_curve[-1][0] if equity_curve else start
        )

        metrics = calculate_metrics(
            strategy_name=self.config.strategy_name,
            initial_balance=self.config.initial_balance,
            final_balance=final_balance,
            equity_curve=equity_curve,
            trades=trades,
            breaches=breaches,
            profit_target_pct=self.config.profit_target_pct,
            max_dd_pct=self.config.max_dd_pct,
            min_trading_days=self.config.min_trading_days,
        )

        return BacktestResult(
            strategy_name=self.config.strategy_name,
            start=start,
            end=end,
            initial_balance=self.config.initial_balance,
            final_balance=final_balance,
            equity_curve=equity_curve,
            trades=trades,
            breaches=breaches,
            indicators=indicators,
            metrics=metrics,
        )

    def _select_equity_curve(self) -> list[tuple[datetime, Decimal]]:
        """Equity recorder's curve when non-empty, else prop-firm actor's."""
        if self._equity_recorder is not None:
            curve = self._equity_recorder.equity_curve
            if curve:
                return curve
        if self._prop_firm_actor is not None:
            return self._prop_firm_actor.equity_curve
        return []

    def _extract_trades(self) -> list[TradeRecord]:
        """Convert Nautilus closed positions into our ``TradeRecord`` list.

        Only fully-closed positions contribute — open positions have no
        ``avg_px_close`` or ``realized_pnl`` yet. Ns timestamps are
        converted to UTC-aware datetimes via ``datetime.fromtimestamp`` so
        TradeRecord.entry_ts / exit_ts stay tz-aware.
        """
        try:
            positions = self._engine.cache.positions_closed()
        except Exception:
            # Cache may be empty or unavailable mid-construction — return [].
            return []

        records: list[TradeRecord] = []
        for pos in positions:
            # A CLOSED position reports ``side == PositionSide.FLAT`` —
            # comparing against LONG here mislabelled every closed trade
            # as SELL. ``pos.entry`` is the entry order's side and is
            # stable for the position's whole lifecycle.
            side = "BUY" if pos.entry == OrderSide.BUY else "SELL"
            # A CLOSED position's ``quantity`` is its REMAINING size — 0.
            # The traded size lives on ``peak_qty`` (max filled quantity),
            # which is also the honest figure for scale-out trades. Only
            # substitute when quantity reads zero so open/partial mocks
            # keep their explicit quantity. NOTE: peak_qty assumes no
            # re-entry after a full close within one position id — no
            # current strategy does this (one bracket per position).
            quantity = Decimal(str(pos.quantity))
            if quantity == 0:
                peak_qty = getattr(pos, "peak_qty", None)
                if peak_qty is not None:
                    quantity = Decimal(str(peak_qty))
            entry_ts = _ns_to_utc(pos.ts_opened)
            exit_ts = _ns_to_utc(pos.ts_closed or pos.ts_last)
            sl_price, tp_price, sl_updates = _extract_bracket_levels(
                self._engine.cache, pos.id
            )
            records.append(
                TradeRecord(
                    trade_id=str(pos.id),
                    symbol=str(pos.instrument_id),
                    side=side,
                    entry_ts=entry_ts,
                    exit_ts=exit_ts,
                    entry_price=Decimal(str(pos.avg_px_open)),
                    exit_price=Decimal(str(pos.avg_px_close or pos.avg_px_open)),
                    quantity=quantity,
                    pnl=_pos_pnl_decimal(pos.realized_pnl),
                    sl_price=sl_price,
                    tp_price=tp_price,
                    sl_updates=sl_updates,
                )
            )
        return records

    def dispose(self) -> None:
        """Release the underlying engine's resources."""
        self._engine.dispose()
